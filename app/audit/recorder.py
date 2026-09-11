"""Audit recorder: the only writer of ``audit_logs`` and ``security_events``."""

from __future__ import annotations

from typing import Any

from flask import g, has_request_context, request

from app.config.logging import current_context, get_logger, redact
from app.extensions import db
from app.models.audit import AuditLog, SecurityEvent
from app.models.enums import AuditResult, SecurityEventSeverity
from app.utils.time import utcnow

log = get_logger("scarlet.audit")

SENSITIVE_KEYS = {"password", "passphrase", "private_key", "secret", "token", "kubeconfig", "encrypted_secret", "value"}


def scrub(details: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove secret-looking keys from audit details recursively."""
    if not details:
        return details
    out: dict[str, Any] = {}
    for key, value in details.items():
        lowered = str(key).lower()
        if any(s in lowered for s in SENSITIVE_KEYS) and lowered not in {"secret_keys", "value_type", "is_secret", "token_prefix", "key_fingerprint", "key_type"}:
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            out[key] = scrub(value)
        elif isinstance(value, str):
            out[key] = redact(value)[:2000]
        elif isinstance(value, list):
            out[key] = [scrub(v) if isinstance(v, dict) else (redact(v)[:500] if isinstance(v, str) else v) for v in value[:100]]
        else:
            out[key] = value
    return out


def _request_meta() -> tuple[str | None, str | None]:
    ip = None
    request_id = current_context().get("request_id")
    if has_request_context():
        ip = request.remote_addr
        request_id = request_id or getattr(g, "request_id", None)
    return ip, request_id


class AuditRecorder:
    def record(
        self,
        action: str,
        *,
        user=None,
        result: AuditResult | str = AuditResult.SUCCESS,
        entity_type: str | None = None,
        entity_id: Any = None,
        target=None,
        application=None,
        environment: str | None = None,
        details: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> AuditLog:
        if user is None:
            from app.security.rbac import get_current_user

            try:
                user = get_current_user()
            except Exception:  # noqa: BLE001
                user = None
        ip, request_id = _request_meta()
        entry = AuditLog(
            timestamp=utcnow(),
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None) or ("system" if user is None else None),
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            target_id=getattr(target, "id", None),
            target_name=getattr(target, "name", None),
            application_id=getattr(application, "id", None),
            application_code=getattr(application, "code", None),
            environment=environment or (target.environment.code if target is not None and getattr(target, "environment", None) else None),
            result=result.value if isinstance(result, AuditResult) else str(result),
            ip_address=ip,
            request_id=request_id,
            details=scrub(details),
        )
        db.session.add(entry)
        if commit:
            db.session.commit()
        log.info("audit %s %s", action, entry.result, extra={"extra_data": {"audit_action": action, "entity_type": entity_type, "entity_id": entry.entity_id, "result": entry.result}})
        return entry

    def security_event(
        self,
        event_type: str,
        message: str,
        *,
        severity: SecurityEventSeverity | str = SecurityEventSeverity.MEDIUM,
        user=None,
        target=None,
        details: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> SecurityEvent:
        ip, request_id = _request_meta()
        event = SecurityEvent(
            timestamp=utcnow(),
            severity=severity.value if isinstance(severity, SecurityEventSeverity) else str(severity),
            event_type=event_type,
            message=redact(message)[:2000],
            user_id=getattr(user, "id", None),
            target_id=getattr(target, "id", None),
            ip_address=ip,
            request_id=request_id,
            details=scrub(details),
        )
        db.session.add(event)
        if commit:
            db.session.commit()
        log.warning("security event %s: %s", event_type, message, extra={"extra_data": {"event_type": event_type, "severity": event.severity}})
        return event


audit = AuditRecorder()
