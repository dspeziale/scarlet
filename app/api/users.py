"""User and role administration endpoints."""

from __future__ import annotations

from flask import request

from app.api import api
from app.api.responses import created, json_body, list_params, ok, paged, parse_bool
from app.errors import ValidationError
from app.repositories import RoleRepository, UserRepository
from app.security.rbac import PERMISSIONS, get_current_user, require_permission
from app.services.auth_service import AuthService
from app.services.user_service import UserService


@api.get("/users")
@require_permission("user.manage")
def list_users():
    params = list_params(default_sort="username")
    return paged(UserRepository().list(**params))


@api.post("/users")
@require_permission("user.manage")
def create_user():
    data = json_body()
    user = UserService().create_user(
        username=str(data.get("username", "")),
        password=str(data.get("password", "")),
        roles=list(data.get("roles") or []),
        email=data.get("email"),
        full_name=str(data.get("full_name", "")),
        must_change_password=parse_bool(data.get("must_change_password", True), default=True),
        actor=get_current_user(),
    )
    return created(user.to_dict())


@api.get("/users/<int:user_id>")
@require_permission("user.manage")
def get_user(user_id: int):
    user = UserRepository().get_or_404(user_id, "User")
    data = user.to_dict()
    data["permissions"] = sorted(user.permission_codes)
    data["locked"] = user.is_locked
    return ok(data)


@api.put("/users/<int:user_id>")
@api.patch("/users/<int:user_id>")
@require_permission("user.manage")
def update_user(user_id: int):
    data = json_body()
    allowed = {
        k: data[k]
        for k in ("email", "full_name", "is_active", "roles", "must_change_password", "unlock")
        if k in data
    }
    user = UserService().update_user(
        UserRepository().get_or_404(user_id, "User"), actor=get_current_user(), **allowed
    )
    return ok(user.to_dict())


@api.delete("/users/<int:user_id>")
@require_permission("user.manage")
def delete_user(user_id: int):
    UserService().delete_user(
        UserRepository().get_or_404(user_id, "User"), actor=get_current_user()
    )
    return ok({"deleted": True})


@api.post("/users/<int:user_id>/reset-password")
@require_permission("user.manage")
def reset_password(user_id: int):
    data = json_body()
    target = UserRepository().get_or_404(user_id, "User")
    AuthService().admin_reset_password(
        get_current_user(),
        target,
        str(data.get("new_password", "")),
        must_change=parse_bool(data.get("must_change_password", True), default=True),
    )
    return ok({"reset": True})


@api.get("/roles")
@require_permission("user.manage")
def list_roles():
    roles = RoleRepository().all()
    return ok(
        [
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "is_system": r.is_system,
                "permissions": sorted(r.permission_codes()),
                "user_count": len(r.users),
            }
            for r in roles
        ]
    )


@api.post("/roles")
@require_permission("user.manage")
def create_role():
    data = json_body()
    role = UserService().create_role(
        name=str(data.get("name", "")),
        description=str(data.get("description", "")),
        permissions=list(data.get("permissions") or []),
        actor=get_current_user(),
    )
    return created(
        {"id": role.id, "name": role.name, "permissions": sorted(role.permission_codes())}
    )


@api.put("/roles/<int:role_id>")
@require_permission("user.manage")
def update_role(role_id: int):
    data = json_body()
    role = UserService().update_role(
        RoleRepository().get_or_404(role_id, "Role"),
        description=data.get("description"),
        permissions=data.get("permissions"),
        actor=get_current_user(),
    )
    return ok({"id": role.id, "name": role.name, "permissions": sorted(role.permission_codes())})


@api.delete("/roles/<int:role_id>")
@require_permission("user.manage")
def delete_role(role_id: int):
    UserService().delete_role(
        RoleRepository().get_or_404(role_id, "Role"), actor=get_current_user()
    )
    return ok({"deleted": True})


@api.get("/permissions")
@require_permission("user.manage")
def list_permissions():
    if request.args.get("grouped"):
        grouped: dict[str, list] = {}
        for code, desc in PERMISSIONS.items():
            grouped.setdefault(code.split(".")[0], []).append({"code": code, "description": desc})
        return ok(grouped)
    return ok([{"code": c, "description": d} for c, d in PERMISSIONS.items()])


@api.get("/users/check-username")
@require_permission("user.manage")
def check_username():
    username = (request.args.get("username") or "").strip()
    if not username:
        raise ValidationError("username required")
    return ok({"available": UserRepository().by_username(username) is None})
