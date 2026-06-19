"""RBAC decorators — wraps flask_jwt_extended.jwt_required."""

from __future__ import annotations

import functools
from typing import Callable

import structlog
from flask import jsonify, g
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from app.extensions import db
from app.models.user import User

log = structlog.get_logger(__name__)

# Role name constants
SUPERADMIN = "SuperAdmin"
TENANT_ADMIN = "TenantAdmin"
OPERATOR = "Operator"
READONLY = "ReadOnly"


def _load_user(user_id: str) -> User | None:
    return db.session.get(User, user_id)


def jwt_required_with_user(fn: Callable) -> Callable:
    """Verify JWT and attach current user to flask.g."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        user_id = get_jwt_identity()
        user = _load_user(user_id)
        if not user or not user.is_active:
            return jsonify(error="forbidden", message="User not found or inactive"), 403
        if user.is_locked():
            return jsonify(error="account_locked", message="Account is temporarily locked"), 403
        g.current_user = user
        return fn(*args, **kwargs)
    return wrapper


def require_role(*role_names: str) -> Callable:
    """Decorator: JWT required + at least one of the listed roles (or SuperAdmin)."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        @jwt_required_with_user
        def wrapper(*args, **kwargs):
            user: User = g.current_user
            if user.is_superadmin:
                return fn(*args, **kwargs)
            if not any(user.has_role(r) for r in role_names):
                log.warning("rbac_denied", user_id=user.id, required_roles=role_names)
                return jsonify(error="forbidden", message="Insufficient role"), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_permission(resource: str, action: str) -> Callable:
    """Decorator: JWT required + specific permission."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        @jwt_required_with_user
        def wrapper(*args, **kwargs):
            user: User = g.current_user
            if not user.has_permission(resource, action):
                log.warning("permission_denied", user_id=user.id, resource=resource, action=action)
                return jsonify(error="forbidden", message="Permission denied"), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_superadmin(fn: Callable) -> Callable:
    @functools.wraps(fn)
    @jwt_required_with_user
    def wrapper(*args, **kwargs):
        user: User = g.current_user
        if not user.is_superadmin:
            return jsonify(error="forbidden", message="SuperAdmin access required"), 403
        return fn(*args, **kwargs)
    return wrapper


def require_tenant_admin_or_above(fn: Callable) -> Callable:
    @functools.wraps(fn)
    @jwt_required_with_user
    def wrapper(*args, **kwargs):
        user: User = g.current_user
        if user.is_superadmin or user.has_role(TENANT_ADMIN):
            return fn(*args, **kwargs)
        return jsonify(error="forbidden", message="TenantAdmin or higher required"), 403
    return wrapper


def same_tenant_required(fn: Callable) -> Callable:
    """Ensures non-superadmin can only access their own tenant's resources."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from app.tenants.context import get_tenant_id
        user: User = g.current_user
        if user.is_superadmin:
            return fn(*args, **kwargs)
        requested_tenant_id = kwargs.get("tenant_id") or get_tenant_id()
        if requested_tenant_id and user.tenant_id != requested_tenant_id:
            return jsonify(error="forbidden", message="Cross-tenant access denied"), 403
        return fn(*args, **kwargs)
    return wrapper
