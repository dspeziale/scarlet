"""
Before-request hook that extracts tenant context from the JWT and sets g.tenant_id.
Every protected endpoint must call this (it is registered as a before_request on the API blueprint).
"""

from __future__ import annotations

import structlog
from flask import g, jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app.tenants.context import set_tenant_id

log = structlog.get_logger(__name__)


def inject_tenant_context() -> None:
    """
    Called as a before_request handler on the /api/v1 blueprint.
    Reads the current user from the JWT and sets g.tenant_id.
    Unauthenticated routes (login, probe registration) must be excluded via
    flask_jwt_extended.jwt_required on individual views.
    """
    try:
        verify_jwt_in_request(optional=True)
        user_id = get_jwt_identity()
        if user_id:
            from app.extensions import db
            from app.models.user import User
            user = db.session.get(User, user_id)
            if user:
                g.current_user = user
                if not user.is_superadmin:
                    set_tenant_id(user.tenant_id)
                else:
                    # SuperAdmin — tenant_id may be overridden per-request via query param
                    set_tenant_id(None)
                log.debug("tenant_context_set", user_id=user_id, tenant_id=user.tenant_id)
    except Exception:
        # JWT absent or invalid — let individual routes enforce auth
        pass
