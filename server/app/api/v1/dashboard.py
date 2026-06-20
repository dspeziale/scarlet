"""
/api/v1/dashboard/stats — aggregated metrics for the main dashboard
(cards, charts, and the probe map). Tenant-scoped; SuperAdmin sees all.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

from flask import g, jsonify, request
from sqlalchemy import select, func

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_role, SUPERADMIN, TENANT_ADMIN, OPERATOR
from app.extensions import db
from app.models.probe import Probe
from app.models.task import Task, TaskAssignment
from app.models.telemetry import DeviceInventory, WifiInventory, BLEInventory
from app.models.ids import IdsAlert


def _scope(stmt, model, tenant_id):
    return stmt if tenant_id is None else stmt.where(model.tenant_id == tenant_id)


@api_v1_bp.get("/system/status")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def system_status():
    """Detailed system/app status: server info, counts and per-probe agent state."""
    from flask import current_app
    from datetime import datetime, timedelta, timezone
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.models.ids import IdsAlert
    from app.models.telemetry import WifiInventory, BLEInventory

    user = g.current_user
    tenant_id = None if user.is_superadmin else user.tenant_id
    now = datetime.now(timezone.utc)

    probes = list(db.session.execute(_scope(select(Probe), Probe, tenant_id)).scalars())
    online = 0
    probe_rows = []
    for p in probes:
        is_online = p.status == "online"
        if is_online:
            online += 1
        # "container running" ≈ heartbeat seen recently
        running = bool(p.last_seen and (now - (p.last_seen if p.last_seen.tzinfo else p.last_seen.replace(tzinfo=timezone.utc))).total_seconds() < 180)
        probe_rows.append({
            "id": p.id, "name": p.name or p.hostname, "hostname": p.hostname,
            "status": p.status, "container_running": running,
            "agent_version": p.agent_version, "platform": p.platform,
            "architecture": p.architecture, "ids_interface": p.ids_interface,
            "location": p.location, "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            "key_provisioned": p.key_provisioned,
        })

    def _count(model):
        return db.session.execute(_scope(select(func.count(model.id)), model, tenant_id)).scalar_one()

    counts = {
        "probes_total": len(probes),
        "probes_online": online,
        "containers_running": sum(1 for r in probe_rows if r["container_running"]),
        "devices": _count(DeviceInventory),
        "wifi": _count(WifiInventory),
        "ble": _count(BLEInventory),
        "tasks_active": db.session.execute(_scope(
            select(func.count(Task.id)).where(Task.status.in_(("queued", "assigned", "running"))),
            Task, tenant_id)).scalar_one(),
        "alerts_24h": db.session.execute(_scope(
            select(func.count(IdsAlert.id)).where(IdsAlert.received_at >= now - timedelta(hours=24)),
            IdsAlert, tenant_id)).scalar_one(),
    }
    app_info = {
        "name": "SOC Seattle",
        "version": "1.0.0",
        "environment": current_app.config.get("ENV") or current_app.config.get("FLASK_ENV") or "production",
        "server_time": now.isoformat(),
    }
    if user.is_superadmin:
        counts["tenants"] = db.session.execute(select(func.count(Tenant.id))).scalar_one()
        counts["users"] = db.session.execute(select(func.count(User.id))).scalar_one()

    return jsonify({"app": app_info, "counts": counts, "probes": probe_rows}), 200


@api_v1_bp.get("/dashboard/stats")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def dashboard_stats():
    user = g.current_user
    if user.is_superadmin:
        tenant_id = request.args.get("tenant_id")  # None => all tenants
    else:
        tenant_id = user.tenant_id

    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)

    # ── Probes (also feeds the map) ──────────────────────────────────────────
    probes = list(db.session.execute(_scope(select(Probe), Probe, tenant_id)).scalars())
    probes_online = sum(1 for p in probes if p.status == "online")
    probe_points = [
        {
            "id": p.id, "name": p.name or p.hostname, "hostname": p.hostname,
            "status": p.status, "lat": p.latitude, "lon": p.longitude,
            "location": p.location, "ids_interface": p.ids_interface,
        }
        for p in probes
    ]

    # ── Simple counts ────────────────────────────────────────────────────────
    def _count(model):
        return db.session.execute(_scope(select(func.count(model.id)), model, tenant_id)).scalar_one()

    devices_total = _count(DeviceInventory)
    wifi_total = _count(WifiInventory)
    ble_total = _count(BLEInventory)

    active_tasks = db.session.execute(
        _scope(select(func.count(Task.id)).where(Task.status.in_(("queued", "assigned", "running"))),
               Task, tenant_id)
    ).scalar_one()

    # ── Alerts: 24h count, timeline, top signatures ──────────────────────────
    alert_stmt = _scope(select(IdsAlert.received_at, IdsAlert.signature, IdsAlert.severity)
                        .where(IdsAlert.received_at >= since_24h), IdsAlert, tenant_id)
    alert_rows = db.session.execute(alert_stmt).all()

    buckets = Counter()
    sig_counter = Counter()
    sev_counter = Counter()
    for received_at, signature, severity in alert_rows:
        if received_at:
            hour = received_at.replace(minute=0, second=0, microsecond=0)
            buckets[hour.isoformat()] += 1
        sig_counter[signature or "—"] += 1
        sev_counter[severity if severity is not None else 0] += 1

    timeline = [{"hour": (since_24h + timedelta(hours=i)).replace(minute=0, second=0, microsecond=0).isoformat(),
                 "count": 0} for i in range(25)]
    by_hour = {b["hour"]: b for b in timeline}
    for iso, c in buckets.items():
        if iso in by_hour:
            by_hour[iso]["count"] = c

    top_signatures = [{"signature": s, "count": c} for s, c in sig_counter.most_common(6)]

    # ── Device vendors (top) ────────────────────────────────────────────────
    vendor_rows = db.session.execute(
        _scope(select(DeviceInventory.vendor, func.count(DeviceInventory.id)), DeviceInventory, tenant_id)
        .group_by(DeviceInventory.vendor)
    ).all()
    vendors = sorted(
        [{"vendor": v or "Unknown", "count": c} for v, c in vendor_rows],
        key=lambda x: x["count"], reverse=True,
    )[:8]

    # ── Task status breakdown ───────────────────────────────────────────────
    status_rows = db.session.execute(
        _scope(select(Task.status, func.count(Task.id)), Task, tenant_id).group_by(Task.status)
    ).all()
    task_status = {s: c for s, c in status_rows}

    return jsonify({
        "counts": {
            "probes_total": len(probes),
            "probes_online": probes_online,
            "active_tasks": active_tasks,
            "devices_total": devices_total,
            "wifi_total": wifi_total,
            "ble_total": ble_total,
            "alerts_24h": len(alert_rows),
        },
        "probes": probe_points,
        "alerts_timeline": timeline,
        "top_signatures": top_signatures,
        "alert_severity": [{"severity": k, "count": v} for k, v in sorted(sev_counter.items())],
        "device_vendors": vendors,
        "task_status": task_status,
    }), 200
