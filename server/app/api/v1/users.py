"""
/api/v1/users  — TenantAdmin manages users in own tenant; SuperAdmin manages all.
"""

from flask import g, jsonify, request

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_role, require_superadmin, TENANT_ADMIN, SUPERADMIN
from app.services.user_service import UserService

_svc = UserService()


@api_v1_bp.get("/users")
@require_role(SUPERADMIN, TENANT_ADMIN)
def list_users():
    user = g.current_user
    tenant_id = request.args.get("tenant_id") or user.tenant_id
    # Non-superadmin can only see their own tenant
    if not user.is_superadmin:
        tenant_id = user.tenant_id
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))
    users = _svc.list_users(tenant_id, limit=limit, offset=offset)
    return jsonify([u.to_dict() for u in users]), 200


@api_v1_bp.post("/users")
@require_role(SUPERADMIN, TENANT_ADMIN)
def create_user():
    user = g.current_user
    body = request.get_json(silent=True) or {}

    email = body.get("email", "").strip().lower()
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not all([email, username, password]):
        return jsonify(error="validation_error", message="email, username, password required"), 400

    # TenantAdmin can only create in own tenant
    tenant_id = body.get("tenant_id") if user.is_superadmin else user.tenant_id

    try:
        new_user = _svc.create_user(
            email=email,
            username=username,
            password=password,
            tenant_id=tenant_id,
            first_name=body.get("first_name"),
            last_name=body.get("last_name"),
            role_names=body.get("roles", []),
        )
        return jsonify(new_user.to_dict()), 201
    except ValueError as e:
        return jsonify(error="conflict", message=str(e)), 409


@api_v1_bp.get("/users/<user_id>")
@require_role(SUPERADMIN, TENANT_ADMIN)
def get_user(user_id: str):
    try:
        target = _svc.get_user(user_id)
        calling = g.current_user
        if not calling.is_superadmin and target.tenant_id != calling.tenant_id:
            return jsonify(error="forbidden"), 403
        return jsonify(target.to_dict()), 200
    except ValueError as e:
        return jsonify(error="not_found", message=str(e)), 404


@api_v1_bp.patch("/users/<user_id>")
@require_role(SUPERADMIN, TENANT_ADMIN)
def update_user(user_id: str):
    body = request.get_json(silent=True) or {}
    try:
        user = _svc.update_user(user_id, g.current_user, **body)
        return jsonify(user.to_dict()), 200
    except (ValueError, PermissionError) as e:
        return jsonify(error="error", message=str(e)), 400


@api_v1_bp.post("/users/<user_id>/roles")
@require_role(SUPERADMIN, TENANT_ADMIN)
def assign_role(user_id: str):
    body = request.get_json(silent=True) or {}
    role = body.get("role")
    if not role:
        return jsonify(error="validation_error", message="role required"), 400
    try:
        user = _svc.assign_role(user_id, role)
        return jsonify(user.to_dict()), 200
    except ValueError as e:
        return jsonify(error="error", message=str(e)), 400
