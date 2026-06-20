"""
/api/v1/probes  — probe management, registration, key provisioning, heartbeat, tasks.

Public endpoints (no JWT):
  POST /api/v1/probes/register
  POST /api/v1/probes/<probe_id>/provision

Probe-authenticated endpoints (JWT issued during registration):
  POST /api/v1/probes/<probe_id>/heartbeat
  GET  /api/v1/probes/<probe_id>/tasks/pending
  POST /api/v1/probes/<probe_id>/tasks/<task_id>/result
  GET  /api/v1/probes/<probe_id>/ids/config

User-authenticated endpoints:
  GET  /api/v1/probes
  GET  /api/v1/probes/<probe_id>
  POST /api/v1/probe-tokens
  GET  /api/v1/probe-tokens
"""

import uuid as _uuid

from flask import g, jsonify, request
from flask_jwt_extended import create_access_token

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_role, require_tenant_admin_or_above, TENANT_ADMIN, OPERATOR, SUPERADMIN
from app.services.probe_service import ProbeService

import structlog
log = structlog.get_logger(__name__)

_svc = ProbeService()


def _persist_network(probe, network: dict | None) -> None:
    """Store interfaces + subnets reported by a probe (no commit)."""
    if not isinstance(network, dict):
        return
    from datetime import datetime, timezone
    interfaces = network.get("interfaces")
    subnets = network.get("subnets")
    if interfaces is not None:
        probe.interfaces = interfaces
    if subnets is not None:
        probe.subnets = subnets
    if interfaces is not None or subnets is not None:
        probe.network_updated_at = datetime.now(timezone.utc)


# ── Public: Registration ────────────────────────────────────────────────────

@api_v1_bp.post("/probes/register")
def probe_register():
    """
    Phase 1: validate registration token and create probe record.
    hostname and machine_id are optional — defaults are generated if absent.
    """
    body = request.get_json(silent=True) or {}
    token_str = body.get("registration_token")
    if not token_str:
        return jsonify(error="validation_error", message="registration_token required"), 400

    data = {
        "registration_token": token_str,
        "hostname": body.get("hostname") or "probe-docker",
        "machine_id": body.get("machine_id") or str(_uuid.uuid4()),
        "agent_version": body.get("agent_version"),
        "platform": body.get("platform"),
        "architecture": body.get("architecture"),
        "network": body.get("network"),
    }

    try:
        result = _svc.register_probe(data)
    except ValueError as e:
        return jsonify(error="registration_failed", message=str(e)), 400

    # Issue a probe-scoped JWT so the agent can authenticate subsequent calls
    probe_id = result["probe_id"]
    result["access_token"] = create_access_token(identity=f"probe:{probe_id}")
    return jsonify(result), 201


@api_v1_bp.post("/probes/<probe_id>/provision")
def probe_provision(probe_id: str):
    """
    Phase 2: X25519 DH handshake — probe sends public keys, server returns its own.
    Accepts both 'sign_public_key' (agent) and 'probe_sign_public_key' (legacy) field names.
    """
    body = request.get_json(silent=True) or {}
    sign_pub = body.get("sign_public_key") or body.get("probe_sign_public_key")
    exchange_pub = body.get("exchange_public_key") or body.get("probe_exchange_public_key")

    if not sign_pub or not exchange_pub:
        return jsonify(
            error="validation_error",
            message="sign_public_key and exchange_public_key required"
        ), 400

    try:
        result = _svc.provision_keys(probe_id, sign_pub, exchange_pub)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="provisioning_failed", message=str(e)), 400


# ── Probe: Heartbeat ────────────────────────────────────────────────────────

@api_v1_bp.post("/probes/<probe_id>/heartbeat")
def probe_heartbeat(probe_id: str):
    """Probe reports liveness — updates last_seen, status and network inventory."""
    from datetime import datetime, timezone
    from app.extensions import db
    from app.models.probe import Probe

    try:
        probe = db.session.get(Probe, probe_id)
        if not probe:
            return jsonify(error="not_found"), 404
        if not probe.enabled:
            return jsonify(error="probe_disabled"), 403

        probe.last_seen = datetime.now(timezone.utc)
        probe.status = "online"

        body = request.get_json(silent=True) or {}
        _persist_network(probe, body.get("network"))

        db.session.commit()
        return jsonify({"status": probe.status, "probe_id": probe.id}), 200
    except Exception as exc:
        log.error("heartbeat_db_error", probe_id=probe_id, error=str(exc))
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify(error="internal_error", message=str(exc)), 500


# ── Probe: Tasks ────────────────────────────────────────────────────────────

@api_v1_bp.get("/probes/<probe_id>/tasks/pending")
def probe_tasks_pending(probe_id: str):
    """Return assigned tasks for the probe in agent-compatible format."""
    from app.extensions import db
    from app.models.probe import Probe
    from app.services.task_service import TaskService

    probe = db.session.get(Probe, probe_id)
    if not probe:
        return jsonify({"tasks": []}), 200

    try:
        assignments = TaskService().get_pending_tasks(probe_id, probe.tenant_id)
        tasks = [
            {
                "id": a.id,                      # assignment_id — used as task_id by the agent
                "type": a.task.task_type,
                "payload": a.task.parameters or {},
                "priority": a.task.priority,
                "name": a.task.name,
            }
            for a in assignments
        ]
        return jsonify({"tasks": tasks}), 200
    except Exception as exc:
        log.error("task_poll_error", probe_id=probe_id, error=str(exc))
        return jsonify({"tasks": []}), 200


@api_v1_bp.post("/probes/<probe_id>/tasks/<assignment_id>/result")
def probe_task_result(probe_id: str, assignment_id: str):
    """Probe reports the result of an executed task."""
    from app.services.task_service import TaskService

    body = request.get_json(silent=True) or {}
    result_payload = body.get("result", {})

    if isinstance(result_payload, dict):
        raw_status = result_payload.get("status", "completed")
        status = "completed" if raw_status in ("ok", "completed") else "failed"
    else:
        status = "completed"
        result_payload = {"raw": str(result_payload)}

    try:
        result = TaskService().submit_result(
            assignment_id=assignment_id,
            probe_id=probe_id,
            status=status,
            result_data=result_payload,
        )
        log.info("task_result_stored", assignment_id=assignment_id, status=status)
        # Populate device inventory from network-discovery style results.
        if status == "completed" and isinstance(result_payload, dict):
            _ingest_discovery(result, probe_id, result_payload)
    except Exception as exc:
        log.warning("task_result_store_failed", assignment_id=assignment_id, error=str(exc))

    return jsonify({"ok": True}), 200


# Task types whose nmap output feeds the device inventory.
_DISCOVERY_TASKS = {"network_discovery", "service_detection", "os_fingerprinting"}


def _ingest_discovery(result, probe_id: str, result_payload: dict) -> None:
    """Parse a completed task result and populate the relevant inventory table."""
    try:
        task = result.assignment.task if result and result.assignment else None
        if not task:
            return
        ttype = task.task_type
        from app.services.telemetry_service import TelemetryService
        tsvc = TelemetryService()

        if ttype in _DISCOVERY_TASKS:
            output = result_payload.get("output")
            if not output:
                return
            from app.services.nmap_parser import parse_nmap_hosts
            devices = parse_nmap_hosts(output)
            if not devices:
                return
            counts = tsvc.upsert_devices(result.tenant_id, probe_id, devices)
            log.info("discovery_devices_ingested", probe_id=probe_id, **counts)
            if counts.get("added"):
                _notify_new_devices(result.tenant_id, probe_id, counts["added"])

        elif ttype == "wifi_scan":
            from app.services.nmap_parser import parse_iw_scan
            nets = parse_iw_scan(result_payload.get("output", ""))
            if nets:
                counts = tsvc.upsert_wifi(result.tenant_id, probe_id, nets)
                log.info("wifi_ingested", probe_id=probe_id, **counts)

        elif ttype == "ble_scan":
            devices = result_payload.get("devices") or []
            if devices:
                counts = tsvc.upsert_ble(result.tenant_id, probe_id, devices)
                log.info("ble_ingested", probe_id=probe_id, **counts)
    except Exception as exc:
        log.warning("telemetry_ingest_failed", probe_id=probe_id, error=str(exc))


def _notify_new_devices(tenant_id: str, probe_id: str, added: int) -> None:
    """Best-effort: alert the tenant/probe referente about new devices."""
    try:
        from app.extensions import db
        from app.models.tenant import Tenant
        from app.models.probe import Probe
        from app.services.notification_service import NotificationService
        tenant = db.session.get(Tenant, tenant_id)
        if not tenant or not tenant.notify_enabled:
            return
        probe = db.session.get(Probe, probe_id)
        pname = probe.name or probe.hostname if probe else probe_id
        NotificationService().notify_tenant(
            tenant,
            subject="SOC Seattle — Nuovi dispositivi rilevati",
            message=f"La sonda '{pname}' ha rilevato {added} nuovo/i dispositivo/i in rete.",
            probe=probe,
        )
    except Exception as exc:
        log.warning("notify_new_devices_failed", probe_id=probe_id, error=str(exc))


# ── Probe: IDS config ───────────────────────────────────────────────────────

@api_v1_bp.get("/probes/<probe_id>/ids/config")
def probe_ids_config(probe_id: str):
    """
    Return IDS configuration for the probe. The interface is whatever was chosen
    from the console (None until an operator selects a card) — the agent does
    NOT auto-start Suricata on a default interface.
    """
    from app.extensions import db
    from app.models.probe import Probe
    probe = db.session.get(Probe, probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    return jsonify({
        "interface": probe.ids_interface,
        "bpf_filter": "",
        "capture_mode": "af-packet",
    }), 200


# ── Console: IDS control (start only after a card is chosen) ─────────────────

@api_v1_bp.post("/probes/<probe_id>/ids/start")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def probe_ids_start(probe_id: str):
    """
    Start Suricata on a chosen network interface. The interface MUST be one the
    probe reported; dispatches an ids_start task carrying it to the agent.
    """
    from app.extensions import db
    from app.models.probe import Probe
    from app.services.task_service import TaskService

    user = g.current_user
    probe = db.session.get(Probe, probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    if not user.is_superadmin and probe.tenant_id != user.tenant_id:
        return jsonify(error="forbidden"), 403
    if not probe.enabled:
        return jsonify(error="forbidden", message="Probe is disabled"), 403

    body = request.get_json(silent=True) or {}
    interface = body.get("interface")
    if not interface:
        return jsonify(error="validation_error", message="interface required — choose a network card"), 400

    available = {i.get("name") for i in (probe.interfaces or [])}
    if available and interface not in available:
        return jsonify(
            error="validation_error",
            message=f"interface '{interface}' not among reported interfaces: {sorted(available)}",
        ), 400

    parameters = {
        "interface": interface,
        "bpf_filter": body.get("bpf_filter", ""),
        "capture_mode": body.get("capture_mode", "af-packet"),
    }

    svc = TaskService()
    task = svc.create_task(
        tenant_id=probe.tenant_id,
        created_by=user.id,
        task_type="ids_start",
        parameters=parameters,
        name=f"Start IDS on {interface} ({probe.hostname})",
    )
    assignment = svc.assign_task(task.id, probe_id, probe.tenant_id)

    # Remember the chosen card so /ids/config reflects it.
    probe.ids_interface = interface
    db.session.commit()

    return jsonify({
        "task_id": task.id,
        "assignment_id": assignment.id,
        "interface": interface,
        "status": assignment.status,
    }), 201


@api_v1_bp.post("/probes/<probe_id>/ids/stop")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def probe_ids_stop(probe_id: str):
    """Stop Suricata on the probe — dispatches an ids_stop task."""
    from app.extensions import db
    from app.models.probe import Probe
    from app.services.task_service import TaskService

    user = g.current_user
    probe = db.session.get(Probe, probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    if not user.is_superadmin and probe.tenant_id != user.tenant_id:
        return jsonify(error="forbidden"), 403

    svc = TaskService()
    task = svc.create_task(
        tenant_id=probe.tenant_id,
        created_by=user.id,
        task_type="ids_stop",
        parameters={},
        name=f"Stop IDS ({probe.hostname})",
    )
    assignment = svc.assign_task(task.id, probe_id, probe.tenant_id)
    db.session.commit()

    return jsonify({
        "task_id": task.id,
        "assignment_id": assignment.id,
        "status": assignment.status,
    }), 201


# ── User-authenticated: Management ─────────────────────────────────────────

@api_v1_bp.get("/probes")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def list_probes():
    """List probes. Superadmin sees all (or filters by ?tenant_id=); tenant users see their own."""
    from app.extensions import db
    from app.models.probe import Probe as _Probe
    from sqlalchemy import select as _select

    user = g.current_user
    if user.is_superadmin:
        tenant_id = request.args.get("tenant_id")
        if tenant_id:
            probes = _svc.list_probes(tenant_id)
        else:
            probes = list(
                db.session.execute(
                    _select(_Probe).order_by(_Probe.registered_at.desc())
                ).scalars()
            )
    else:
        probes = _svc.list_probes(user.tenant_id)
    return jsonify([p.to_dict() for p in probes]), 200


@api_v1_bp.get("/probes/<probe_id>")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def get_probe(probe_id: str):
    try:
        probe = _svc.get_probe(probe_id)
        user = g.current_user
        if not user.is_superadmin and probe.tenant_id != user.tenant_id:
            return jsonify(error="forbidden"), 403
        return jsonify(probe.to_dict()), 200
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404


@api_v1_bp.patch("/probes/<probe_id>")
@require_role(SUPERADMIN, TENANT_ADMIN)
def update_probe(probe_id: str):
    """Edit probe metadata: name, location (posizione), contact (referente), notes."""
    user = g.current_user
    body = request.get_json(silent=True) or {}
    # Only forward keys actually present, so omitted fields are not wiped.
    _editable = ("name", "location", "latitude", "longitude",
                 "contact_name", "contact_email", "telegram_id", "notes")
    fields = {k: body[k] for k in _editable if k in body}
    try:
        probe = _svc.update_probe(
            probe_id, user.tenant_id, user.is_superadmin, **fields
        )
        return jsonify(probe.to_dict()), 200
    except PermissionError as e:
        return jsonify(error="forbidden", message=str(e)), 403
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404


# ── Token management ────────────────────────────────────────────────────────

@api_v1_bp.post("/probe-tokens")
@require_tenant_admin_or_above
def generate_probe_token():
    """Generate a one-time probe registration token."""
    user = g.current_user
    body = request.get_json(silent=True) or {}
    tenant_id = body.get("tenant_id") if user.is_superadmin else user.tenant_id
    if not tenant_id:
        return jsonify(error="validation_error", message="tenant_id required"), 400

    token = _svc.generate_registration_token(
        tenant_id=tenant_id,
        created_by=user.id,
        label=body.get("label"),
        expiry_hours=body.get("expiry_hours"),
    )
    return jsonify(token.to_dict()), 201


@api_v1_bp.get("/probe-tokens")
@require_tenant_admin_or_above
def list_probe_tokens():
    from app.repositories.probe_repo import ProbeTokenRepository
    user = g.current_user
    tenant_id = request.args.get("tenant_id") if user.is_superadmin else user.tenant_id
    repo = ProbeTokenRepository()
    tokens = repo.list_by_tenant(tenant_id)
    return jsonify([t.to_dict() for t in tokens]), 200


# ── Key rotation (user-initiated) ───────────────────────────────────────────

@api_v1_bp.post("/probes/<probe_id>/rotate-keys")
@require_role(SUPERADMIN, TENANT_ADMIN)
def probe_rotate_keys(probe_id: str):
    """Rotate cryptographic keys for a probe."""
    body = request.get_json(silent=True) or {}
    sign_pub = body.get("sign_public_key") or body.get("probe_sign_public_key")
    exchange_pub = body.get("exchange_public_key") or body.get("probe_exchange_public_key")

    if not sign_pub or not exchange_pub:
        return jsonify(
            error="validation_error",
            message="sign_public_key and exchange_public_key required"
        ), 400

    try:
        result = _svc.rotate_keys(probe_id, sign_pub, exchange_pub)
        return jsonify(result), 200
    except ValueError as e:
        return jsonify(error="error", message=str(e)), 400
