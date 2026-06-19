"""
/api/v1/audit  — audit log queries (read-only).
"""

from flask import g, jsonify, request

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_role, require_superadmin, TENANT_ADMIN, SUPERADMIN
from app.repositories.audit_repo import AuditRepository

_repo = AuditRepository()


@api_v1_bp.get("/audit")
@require_role(SUPERADMIN, TENANT_ADMIN)
def list_audit():
    """
    List audit logs.
    SuperAdmin sees all tenants (or filter via ?tenant_id=).
    TenantAdmin sees only own tenant.
    """
    user = g.current_user
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    if user.is_superadmin:
        tenant_id = request.args.get("tenant_id")
        if tenant_id:
            logs = _repo.list_by_tenant(tenant_id, limit=limit, offset=offset)
        else:
            logs = _repo.list_global(limit=limit, offset=offset)
    else:
        logs = _repo.list_by_tenant(user.tenant_id, limit=limit, offset=offset)

    return jsonify([l.to_dict() for l in logs]), 200


@api_v1_bp.get("/audit/user/<user_id>")
@require_superadmin
def audit_by_user(user_id: str):
    """SuperAdmin: get audit trail for a specific user."""
    limit = int(request.args.get("limit", 100))
    logs = _repo.list_by_user(user_id, limit=limit)
    return jsonify([l.to_dict() for l in logs]), 200
