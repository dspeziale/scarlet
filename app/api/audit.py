"""Audit log endpoints (read-only + export)."""

from __future__ import annotations

from flask import Response, request

from app.api import api
from app.api.responses import list_params, ok, paged
from app.errors import ValidationError
from app.repositories import SecurityEventRepository
from app.security.rbac import get_current_user, require_permission
from app.services.audit_service import AuditService


def _filters() -> dict:
    return {
        "user_id": request.args.get("user_id") or None,
        "action": (request.args.get("action") or "").strip()[:64] or None,
        "entity_type": (request.args.get("entity_type") or "").strip()[:64] or None,
        "entity_id": (request.args.get("entity_id") or "").strip()[:64] or None,
        "environment": (request.args.get("environment") or "").upper() or None,
        "result": (request.args.get("result") or "").upper() or None,
        "date_from": request.args.get("date_from") or None,
        "date_to": request.args.get("date_to") or None,
    }


@api.get("/audit")
@require_permission("audit.view")
def list_audit():
    params = list_params(default_sort="timestamp")
    return paged(AuditService().list(**params, **_filters()))


@api.get("/audit/actions")
@require_permission("audit.view")
def audit_actions():
    return ok(AuditService().actions())


@api.get("/audit/export")
@require_permission("audit.export")
def export_audit():
    fmt = (request.args.get("format") or "csv").lower()
    filters = {k: v for k, v in _filters().items() if v}
    if request.args.get("search"):
        filters["search"] = request.args.get("search")[:200]
    service = AuditService()
    if fmt == "csv":
        body = service.export_csv(filters, user=get_current_user())
        return Response(
            body,
            mimetype="text/csv",
            headers={"Content-Disposition": 'attachment; filename="scarlet-audit.csv"'},
        )
    if fmt == "json":
        body = service.export_json(filters, user=get_current_user())
        return Response(
            body,
            mimetype="application/json",
            headers={"Content-Disposition": 'attachment; filename="scarlet-audit.json"'},
        )
    raise ValidationError("format must be csv or json.")


@api.get("/security-events")
@require_permission("audit.view")
def list_security_events():
    params = list_params(default_sort="timestamp")
    return paged(
        SecurityEventRepository().list(
            **params, severity=(request.args.get("severity") or "").upper() or None
        )
    )


@api.post("/security-events/<int:event_id>/acknowledge")
@require_permission("system.manage")
def acknowledge_event(event_id: int):
    AuditService().acknowledge_event(event_id, user=get_current_user())
    return ok({"acknowledged": True})
