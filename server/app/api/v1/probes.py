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
    """Probe reports liveness — updates last_seen and status directly."""
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
        TaskService().submit_result(
            assignment_id=assignment_id,
            probe_id=probe_id,
            status=status,
            result_data=result_payload,
        )
        log.info("task_result_stored", assignment_id=assignment_id, status=status)
    except Exception as exc:
        log.warning("task_result_store_failed", assignment_id=assignment_id, error=str(exc))

    return jsonify({"ok": True}), 200


# ── Probe: IDS config ───────────────────────────────────────────────────────

@api_v1_bp.get("/probes/<probe_id>/ids/config")
def probe_ids_config(probe_id: str):
    """Return IDS configuration for the probe. Returns defaults if not configured."""
    from app.extensions import db
    from app.models.probe import Probe
    if not db.session.get(Probe, probe_id):
        return jsonify(error="not_found"), 404
    return jsonify({"interface": "any", "bpf_filter": "", "capture_mode": "af-packet"}), 200


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
