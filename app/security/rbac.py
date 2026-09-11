"""Role based access control: permission catalogue, default roles, decorators.

Authorization is enforced server-side in services and route decorators. The UI
only *hides* controls for convenience; every backend entry point re-checks.

Production hardening: for operations on production hosts a matching
``prod.<permission>`` permission is additionally required. OPERATOR has the
DEV permissions but not the PROD variants by default; PROD_OPERATOR and ADMIN do.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import current_app, g, jsonify, redirect, request, url_for
from flask_login import current_user

from app.errors import AuthenticationError, AuthorizationError

# --- permission catalogue -----------------------------------------------------

PERMISSIONS: dict[str, str] = {
    "dashboard.view": "View the dashboard",
    "host.view": "View hosts",
    "host.create": "Create hosts",
    "host.update": "Update hosts",
    "host.delete": "Delete hosts",
    "host.test": "Test connection and discover hosts",
    "host.approve_key": "Approve SSH host keys",
    "credential.manage": "Create, rotate and revoke SSH credentials",
    "application.view": "View applications",
    "application.create": "Create applications",
    "application.update": "Update applications",
    "application.delete": "Delete applications",
    "package.view": "View packages and releases",
    "package.upload": "Upload release packages",
    "package.delete": "Delete invalid packages",
    "deployment.view": "View deployments",
    "deployment.execute": "Execute deployments",
    "deployment.rollback": "Execute rollbacks",
    "deployment.approve": "Approve production deployments",
    "deployment.cancel": "Cancel queued deployments",
    "lifecycle.start": "Start applications",
    "lifecycle.stop": "Stop applications",
    "lifecycle.restart": "Restart applications",
    "lifecycle.status": "Refresh application status",
    "logs.view": "View application logs",
    "logs.download": "Download application/operation logs",
    "health.view": "View health checks",
    "health.execute": "Execute health checks",
    "configuration.view": "View configuration",
    "configuration.update": "Update configuration and secrets",
    "audit.view": "View the audit log",
    "audit.export": "Export the audit log",
    "user.manage": "Manage users and roles",
    "system.manage": "Manage system settings",
    "notification.view": "View notifications",
    # production variants
    "prod.deployment.execute": "Execute deployments on PROD hosts",
    "prod.deployment.rollback": "Execute rollbacks on PROD hosts",
    "prod.lifecycle.start": "Start applications on PROD hosts",
    "prod.lifecycle.stop": "Stop applications on PROD hosts",
    "prod.lifecycle.restart": "Restart applications on PROD hosts",
    "prod.configuration.update": "Update PROD configuration",
    "prod.host.delete": "Delete PROD hosts",
    "prod.host.update": "Update PROD hosts",
}

# Permissions that have a prod-specific variant
PROD_SENSITIVE = {
    "deployment.execute",
    "deployment.rollback",
    "lifecycle.start",
    "lifecycle.stop",
    "lifecycle.restart",
    "configuration.update",
    "host.delete",
    "host.update",
}

ROLE_ADMIN = "ADMIN"
ROLE_OPERATOR = "OPERATOR"
ROLE_PROD_OPERATOR = "PROD_OPERATOR"
ROLE_VIEWER = "VIEWER"
ROLE_AUDITOR = "AUDITOR"

_VIEW_PERMISSIONS = {
    "dashboard.view",
    "host.view",
    "application.view",
    "package.view",
    "deployment.view",
    "logs.view",
    "health.view",
    "configuration.view",
    "notification.view",
}

_OPERATOR_PERMISSIONS = _VIEW_PERMISSIONS | {
    "host.test",
    "package.upload",
    "deployment.execute",
    "deployment.rollback",
    "deployment.cancel",
    "lifecycle.start",
    "lifecycle.stop",
    "lifecycle.restart",
    "lifecycle.status",
    "logs.download",
    "health.execute",
    "configuration.update",
}

DEFAULT_ROLES: dict[str, dict[str, Any]] = {
    ROLE_ADMIN: {
        "description": "Full access to every function, including PROD and system administration",
        "permissions": set(PERMISSIONS),
    },
    ROLE_OPERATOR: {
        "description": "Operate applications on DEV hosts; read-only on PROD",
        "permissions": _OPERATOR_PERMISSIONS,
    },
    ROLE_PROD_OPERATOR: {
        "description": "Operate applications on DEV and PROD hosts",
        "permissions": _OPERATOR_PERMISSIONS
        | {
            "prod.deployment.execute",
            "prod.deployment.rollback",
            "prod.lifecycle.start",
            "prod.lifecycle.stop",
            "prod.lifecycle.restart",
            "prod.configuration.update",
            "deployment.approve",
        },
    },
    ROLE_VIEWER: {
        "description": "Read-only access",
        "permissions": _VIEW_PERMISSIONS,
    },
    ROLE_AUDITOR: {
        "description": "Read-only access plus audit log access and export",
        "permissions": _VIEW_PERMISSIONS | {"audit.view", "audit.export"},
    },
}


# --- checks -------------------------------------------------------------------


def _resolve_user():
    user = getattr(g, "api_user", None)
    if user is not None:
        return user
    if current_user is not None and getattr(current_user, "is_authenticated", False):
        return current_user
    return None


def get_current_user():
    return _resolve_user()


def user_has_permission(user, permission: str, *, production: bool = False) -> bool:
    if user is None or not getattr(user, "is_active", False):
        return False
    codes = user.permission_codes
    if permission not in codes:
        return False
    if production and permission in PROD_SENSITIVE:
        return f"prod.{permission}" in codes
    return True


def check_permission(permission: str, *, production: bool = False, user=None) -> None:
    """Raise AuthenticationError / AuthorizationError when the check fails."""
    user = user or _resolve_user()
    if user is None:
        raise AuthenticationError()
    if not user_has_permission(user, permission, production=production):
        detail = f" on a PRODUCTION target" if production else ""
        raise AuthorizationError(
            f"Permission '{permission}'{detail} is required.",
            details={"permission": permission, "production": production},
        )


def _wants_json() -> bool:
    return request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"


def login_required_any(func: Callable) -> Callable:
    """Require an authenticated session user or API token user."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any):
        if _resolve_user() is None:
            if _wants_json():
                return jsonify({"ok": False, "error": AuthenticationError().to_dict()}), 401
            return redirect(url_for("web_auth.login", next=request.full_path))
        return func(*args, **kwargs)

    return wrapper


def require_permission(*permissions: str) -> Callable:
    """Decorator: the current user must hold *all* listed permissions."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            user = _resolve_user()
            if user is None:
                if _wants_json():
                    return jsonify({"ok": False, "error": AuthenticationError().to_dict()}), 401
                return redirect(url_for("web_auth.login", next=request.full_path))
            for perm in permissions:
                if not user_has_permission(user, perm):
                    current_app.logger.warning(
                        "authorization denied", extra={"extra_data": {"permission": perm}}
                    )
                    raise AuthorizationError(f"Permission '{perm}' is required.")
            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_role(*roles: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any):
            user = _resolve_user()
            if user is None:
                raise AuthenticationError()
            if not any(user.has_role(r) for r in roles):
                raise AuthorizationError()
            return func(*args, **kwargs)

        return wrapper

    return decorator
