"""REST API blueprint (``/api``).

* JSON envelope: ``{"ok": true, "data": ..., "meta": ...}`` / ``{"ok": false, "error": {...}}``
* Authentication: browser session (with CSRF token header) or ``Authorization: Bearer scl_...``
* CSRF is enforced for session-authenticated unsafe requests; token calls are exempt.
"""

from __future__ import annotations

from flask import Blueprint, Flask, current_app, g, request

from app.extensions import csrf, limiter

api = Blueprint("api", __name__, url_prefix="/api")

CSRF_EXEMPT_ENDPOINTS = {"api.login", "api.health", "api.ready", "api.metrics"}


@api.before_request
def _api_csrf() -> None:
    if not current_app.config.get("WTF_CSRF_ENABLED", True):
        return
    if (
        request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and not getattr(g, "api_token", None)
        and request.endpoint not in CSRF_EXEMPT_ENDPOINTS
    ):
        csrf.protect()


def register_api(app: Flask) -> None:
    from app.api import (  # noqa: F401 - route modules register on the blueprint
        applications,
        audit,
        auth,
        deployments,
        health,
        hosts,
        openapi,
        operations,
        packages,
        system,
        users,
    )

    limiter.limit(app.config.get("SCARLET_API_RATE_LIMIT", "600 per minute"))(api)
    app.register_blueprint(api)
