"""
/api/v1/tenants  — SuperAdmin only.
"""

from flask import jsonify, request

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_superadmin
from app.services.tenant_service import TenantService

_svc = TenantService()


@api_v1_bp.get("/tenants")
@require_superadmin
def list_tenants():
    """List all tenants (SuperAdmin only)."""
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))
    tenants = _svc.list_tenants(limit=limit, offset=offset)
    return jsonify([t.to_dict() for t in tenants]), 200


@api_v1_bp.post("/tenants")
@require_superadmin
def create_tenant():
    """Create a new tenant (SuperAdmin only)."""
    body = request.get_json(silent=True) or {}
    name = body.get("name", "").strip()
    if not name:
        return jsonify(error="validation_error", message="name is required"), 400

    try:
        tenant = _svc.create_tenant(
            name=name,
            plan=body.get("plan", "free"),
            max_probes=int(body.get("max_probes", 5)),
            description=body.get("description"),
        )
        return jsonify(tenant.to_dict()), 201
    except ValueError as e:
        return jsonify(error="conflict", message=str(e)), 409


@api_v1_bp.get("/tenants/<tenant_id>")
@require_superadmin
def get_tenant(tenant_id: str):
    try:
        return jsonify(_svc.get_tenant(tenant_id).to_dict()), 200
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404


@api_v1_bp.patch("/tenants/<tenant_id>")
@require_superadmin
def update_tenant(tenant_id: str):
    body = request.get_json(silent=True) or {}
    allowed = {"name", "plan", "max_probes", "description", "is_active"}
    updates = {k: v for k, v in body.items() if k in allowed}
    try:
        tenant = _svc.update_tenant(tenant_id, **updates)
        return jsonify(tenant.to_dict()), 200
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404


@api_v1_bp.delete("/tenants/<tenant_id>")
@require_superadmin
def deactivate_tenant(tenant_id: str):
    try:
        _svc.deactivate_tenant(tenant_id)
        return jsonify(message="Tenant deactivated"), 200
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404
