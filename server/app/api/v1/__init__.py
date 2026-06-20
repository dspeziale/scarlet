"""API v1 blueprint — registers all sub-blueprints and adds before_request hooks."""

from flask import Blueprint

from app.middleware.tenant_isolation import inject_tenant_context

api_v1_bp = Blueprint("api_v1", __name__)

api_v1_bp.before_request(inject_tenant_context)

# Sub-routes
from app.api.v1 import auth, tenants, users, probes, tasks, telemetry, accounting, audit, notifications, ids, dashboard  # noqa: E402, F401
