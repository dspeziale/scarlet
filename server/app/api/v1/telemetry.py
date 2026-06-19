"""
/api/v1/telemetry  — device/service/wifi/ble inventory ingestion + queries.
"""

from flask import g, jsonify, request

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_role, TENANT_ADMIN, OPERATOR, SUPERADMIN
from app.services.telemetry_service import TelemetryService

_svc = TelemetryService()


@api_v1_bp.post("/telemetry/devices")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def ingest_devices():
    """Probe submits discovered device inventory."""
    body = request.get_json(silent=True) or {}
    user = g.current_user
    probe_id = body.get("probe_id")
    devices = body.get("devices", [])
    if not probe_id:
        return jsonify(error="validation_error", message="probe_id required"), 400
    created = _svc.ingest_devices(user.tenant_id, probe_id, devices)
    return jsonify({"ingested": len(created)}), 201


@api_v1_bp.get("/telemetry/devices")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def list_devices():
    user = g.current_user
    tenant_id = request.args.get("tenant_id") if user.is_superadmin else user.tenant_id
    probe_id = request.args.get("probe_id")
    limit = int(request.args.get("limit", 100))
    devices = _svc.list_devices(tenant_id, probe_id=probe_id, limit=limit)
    return jsonify([d.to_dict() for d in devices]), 200


@api_v1_bp.post("/telemetry/services")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def ingest_services():
    body = request.get_json(silent=True) or {}
    user = g.current_user
    probe_id = body.get("probe_id")
    services = body.get("services", [])
    if not probe_id:
        return jsonify(error="validation_error", message="probe_id required"), 400
    created = _svc.ingest_services(user.tenant_id, probe_id, services)
    return jsonify({"ingested": len(created)}), 201


@api_v1_bp.post("/telemetry/wifi")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def ingest_wifi():
    body = request.get_json(silent=True) or {}
    user = g.current_user
    probe_id = body.get("probe_id")
    networks = body.get("networks", [])
    if not probe_id:
        return jsonify(error="validation_error", message="probe_id required"), 400
    created = _svc.ingest_wifi(user.tenant_id, probe_id, networks)
    return jsonify({"ingested": len(created)}), 201


@api_v1_bp.post("/telemetry/ble")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def ingest_ble():
    body = request.get_json(silent=True) or {}
    user = g.current_user
    probe_id = body.get("probe_id")
    devices = body.get("devices", [])
    if not probe_id:
        return jsonify(error="validation_error", message="probe_id required"), 400
    created = _svc.ingest_ble(user.tenant_id, probe_id, devices)
    return jsonify({"ingested": len(created)}), 201
