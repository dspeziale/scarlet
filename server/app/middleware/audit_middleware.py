"""Programmatic audit helpers — called explicitly from service/view layer."""

from __future__ import annotations

import structlog
from flask import g, request

from app.extensions import db
from app.models.audit import AuditLog

log = structlog.get_logger(__name__)


def record_audit(
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    payload: dict | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> AuditLog:
    """Write an immutable audit record. Call this from services/views."""
    current_user = getattr(g, "current_user", None)
    correlation_id = getattr(g, "correlation_id", None)

    entry = AuditLog(
        tenant_id=tenant_id or (current_user.tenant_id if current_user else None),
        user_id=user_id or (current_user.id if current_user else None),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip=_get_ip(),
        user_agent=request.headers.get("User-Agent") if request else None,
        correlation_id=correlation_id,
        payload_json=payload,
    )
    db.session.add(entry)
    log.info("audit", action=action, resource_type=resource_type, resource_id=resource_id)
    return entry


def _get_ip() -> str | None:
    if not request:
        return None
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr
