"""
/api/v1 IDS endpoints.

Probe-facing (no JWT, like heartbeat):
  POST /probes/<id>/ids/alerts        ingest eve.json alert batch
  GET  /probes/<id>/ids/rules         compiled .rules text (ETag: X-Ruleset-Version)

User-facing (JWT + RBAC):
  GET  /probes/<id>/ids/alerts                live alert feed (?since_id=&limit=)
  GET  /probes/<id>/ids/rules/assignments     active rule ids for the probe
  PUT  /probes/<id>/ids/rules/assignments      set active rule ids
  GET  /ids/rules                              tenant rule catalog
  POST /ids/rules                              add a rule
  DELETE /ids/rules/<rule_id>                  remove a rule
"""

from flask import Response, g, jsonify, request

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_role, require_tenant_admin_or_above, SUPERADMIN, TENANT_ADMIN, OPERATOR
from app.extensions import db
from app.models.probe import Probe
from app.services.ids_service import IdsService

import structlog
log = structlog.get_logger(__name__)

_svc = IdsService()


def _probe_or_none(probe_id):
    return db.session.get(Probe, probe_id)


def _check_probe_access(probe):
    user = g.current_user
    if not user.is_superadmin and probe.tenant_id != user.tenant_id:
        return False
    return True


# ── Probe-facing ─────────────────────────────────────────────────────────────

@api_v1_bp.post("/probes/<probe_id>/ids/alerts")
def ids_ingest_alerts(probe_id: str):
    probe = _probe_or_none(probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    body = request.get_json(silent=True) or {}
    alerts = body.get("alerts") or body.get("events") or []
    try:
        n = _svc.ingest_alerts(probe.tenant_id, probe_id, alerts)
    except Exception as exc:
        db.session.rollback()
        log.warning("ids_alert_ingest_failed", probe_id=probe_id, error=str(exc))
        return jsonify(error="ingest_failed"), 200
    return jsonify({"ingested": n}), 201


@api_v1_bp.post("/probes/<probe_id>/traffic")
def ids_ingest_traffic(probe_id: str):
    probe = _probe_or_none(probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    body = request.get_json(silent=True) or {}
    lines = body.get("lines") or []
    try:
        n = _svc.ingest_traffic(probe.tenant_id, probe_id, lines)
    except Exception as exc:
        db.session.rollback()
        log.warning("traffic_ingest_failed", probe_id=probe_id, error=str(exc))
        return jsonify(error="ingest_failed"), 200
    return jsonify({"ingested": n}), 201


@api_v1_bp.get("/probes/<probe_id>/traffic")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def ids_list_traffic(probe_id: str):
    probe = _probe_or_none(probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    if not _check_probe_access(probe):
        return jsonify(error="forbidden"), 403
    since_id = int(request.args.get("since_id", 0))
    limit = min(int(request.args.get("limit", 400)), 800)
    rows = _svc.list_traffic(probe.tenant_id, probe_id, since_id=since_id, limit=limit)
    return jsonify({"lines": [r.to_dict() for r in rows]}), 200


@api_v1_bp.get("/probes/<probe_id>/ids/rules")
def ids_probe_rules(probe_id: str):
    probe = _probe_or_none(probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    text, version = _svc.compile_rules_for_probe(probe.tenant_id, probe_id)
    if not text:
        return jsonify(error="no_ruleset_assigned"), 404
    if request.headers.get("If-None-Match") == version:
        return ("", 304, {"X-Ruleset-Version": version})
    return Response(text, mimetype="text/plain", headers={"X-Ruleset-Version": version})


# ── User-facing: live alerts ─────────────────────────────────────────────────

@api_v1_bp.get("/probes/<probe_id>/ids/alerts")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def ids_list_alerts(probe_id: str):
    probe = _probe_or_none(probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    if not _check_probe_access(probe):
        return jsonify(error="forbidden"), 403
    since_id = int(request.args.get("since_id", 0))
    limit = min(int(request.args.get("limit", 200)), 500)
    alerts = _svc.list_alerts(probe.tenant_id, probe_id, since_id=since_id, limit=limit)
    return jsonify({"alerts": [a.to_dict() for a in alerts]}), 200


# ── User-facing: rule catalog ────────────────────────────────────────────────

@api_v1_bp.get("/ids/rules")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def ids_list_rules():
    user = g.current_user
    tenant_id = request.args.get("tenant_id") if user.is_superadmin else user.tenant_id
    if not tenant_id:
        return jsonify(error="validation_error", message="tenant_id required"), 400
    return jsonify([r.to_dict() for r in _svc.list_rules(tenant_id)]), 200


@api_v1_bp.post("/ids/rules")
@require_tenant_admin_or_above
def ids_create_rule():
    user = g.current_user
    body = request.get_json(silent=True) or {}
    tenant_id = body.get("tenant_id") if user.is_superadmin else user.tenant_id
    rule_text = (body.get("rule_text") or "").strip()
    if not tenant_id or not rule_text:
        return jsonify(error="validation_error", message="tenant_id and rule_text required"), 400
    rule = _svc.create_rule(
        tenant_id, rule_text,
        msg=body.get("msg"), sid=body.get("sid"), category=body.get("category"),
    )
    return jsonify(rule.to_dict()), 201


@api_v1_bp.post("/ids/rules/import")
@require_tenant_admin_or_above
def ids_import_rules():
    """Download a .rules file from a URL and add its rules to the tenant catalog."""
    user = g.current_user
    body = request.get_json(silent=True) or {}
    tenant_id = body.get("tenant_id") if user.is_superadmin else user.tenant_id
    url = (body.get("url") or "").strip()
    if not tenant_id or not url:
        return jsonify(error="validation_error", message="tenant_id and url required"), 400
    try:
        result = _svc.import_rules_from_url(tenant_id, url)
    except ValueError as e:
        return jsonify(error="import_failed", message=str(e)), 400
    return jsonify(result), 200


@api_v1_bp.delete("/ids/rules/<rule_id>")
@require_tenant_admin_or_above
def ids_delete_rule(rule_id: str):
    user = g.current_user
    tenant_id = request.args.get("tenant_id") if user.is_superadmin else user.tenant_id
    try:
        _svc.delete_rule(tenant_id, rule_id)
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404
    return jsonify(message="deleted"), 200


# ── User-facing: per-probe rule assignment ───────────────────────────────────

@api_v1_bp.get("/probes/<probe_id>/ids/rules/assignments")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def ids_get_assignments(probe_id: str):
    probe = _probe_or_none(probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    if not _check_probe_access(probe):
        return jsonify(error="forbidden"), 403
    return jsonify({
        "active_rule_ids": sorted(_svc.get_probe_rule_ids(probe_id)),
        "ruleset_version": probe.ruleset_version,
    }), 200


@api_v1_bp.put("/probes/<probe_id>/ids/rules/assignments")
@require_tenant_admin_or_above
def ids_set_assignments(probe_id: str):
    probe = _probe_or_none(probe_id)
    if not probe:
        return jsonify(error="not_found"), 404
    if not _check_probe_access(probe):
        return jsonify(error="forbidden"), 403
    body = request.get_json(silent=True) or {}
    rule_ids = body.get("rule_ids", [])
    if not isinstance(rule_ids, list):
        return jsonify(error="validation_error", message="rule_ids must be a list"), 400
    _svc.set_probe_rules(probe.tenant_id, probe_id, rule_ids)
    # Use the compiled text + version (only enabled rules) for a consistent ETag.
    text, version = _svc.compile_rules_for_probe(probe.tenant_id, probe_id)
    probe.ruleset_version = version
    db.session.commit()
    # Push the new ruleset to the probe immediately via an ids_rule_deploy task.
    try:
        from app.services.task_service import TaskService
        svc = TaskService()
        task = svc.create_task(
            tenant_id=probe.tenant_id, created_by=g.current_user.id,
            task_type="ids_rule_deploy",
            parameters={"rules_content": text, "version": version},
            name=f"Deploy ruleset {version} to {probe.hostname}",
        )
        svc.assign_task(task.id, probe_id, probe.tenant_id)
    except Exception as exc:
        log.warning("ruleset_deploy_task_failed", probe_id=probe_id, error=str(exc))
    return jsonify({"ruleset_version": version, "count": len(set(rule_ids))}), 200
