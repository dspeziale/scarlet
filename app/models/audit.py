"""Immutable audit log and security events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin
from app.models.enums import AuditResult, SecurityEventSeverity


class AuditLog(PkMixin, Base):
    """Append-only audit record.

    Rows are never updated or deleted through normal application flows; the
    ``AuditRecorder`` is the only writer and no repository exposes update/delete.
    Foreign keys use SET NULL so deleting a user or host never destroys history.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_user_id", "user_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )

    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[int | None] = mapped_column(
        ForeignKey("target_hosts.id", ondelete="SET NULL"), nullable=True
    )
    target_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    application_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    environment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    result: Mapped[str] = mapped_column(String(16), default=AuditResult.SUCCESS.value, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    user = relationship("User")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "target_id": self.target_id,
            "target_name": self.target_name,
            "application_id": self.application_id,
            "application_code": self.application_code,
            "environment": self.environment,
            "result": self.result,
            "ip_address": self.ip_address,
            "request_id": self.request_id,
            "details": self.details or {},
        }


class SecurityEvent(PkMixin, Base):
    """Security-relevant event (host key mismatch, lockout, denied action...)."""

    __tablename__ = "security_events"
    __table_args__ = (Index("ix_security_events_timestamp", "timestamp"),)

    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16), default=SecurityEventSeverity.MEDIUM.value, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_id: Mapped[int | None] = mapped_column(
        ForeignKey("target_hosts.id", ondelete="SET NULL"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "severity": self.severity,
            "event_type": self.event_type,
            "message": self.message,
            "user_id": self.user_id,
            "target_id": self.target_id,
            "ip_address": self.ip_address,
            "request_id": self.request_id,
            "details": self.details or {},
            "acknowledged": self.acknowledged,
            "occurrences": self.occurrences,
        }
