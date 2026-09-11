"""Lifecycle operations, their logs, health check results and distributed locks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin, TimestampMixin
from app.models.enums import HealthStatus, OperationStatus


class LifecycleOperation(PkMixin, TimestampMixin, Base):
    __tablename__ = "lifecycle_operations"
    __table_args__ = (
        Index("ix_lifecycle_operations_status", "status"),
        Index("ix_lifecycle_operations_created_at", "created_at"),
        Index("ix_lifecycle_operations_app_target", "application_id", "target_id"),
    )

    reference: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=OperationStatus.QUEUED.value, nullable=False
    )
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True
    )
    target_id: Mapped[int | None] = mapped_column(
        ForeignKey("target_hosts.id", ondelete="SET NULL"), nullable=True
    )
    instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_instances.id", ondelete="SET NULL"), nullable=True
    )
    deployment_id: Mapped[int | None] = mapped_column(
        ForeignKey("deployments.id", ondelete="SET NULL"), nullable=True
    )
    environment_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    application = relationship("Application")
    target = relationship("TargetHost")
    instance = relationship("ApplicationInstance")
    requested_by = relationship("User")
    logs: Mapped[list[OperationLog]] = relationship(
        back_populates="operation", cascade="all, delete-orphan", order_by="OperationLog.id"
    )

    @property
    def status_enum(self) -> OperationStatus:
        return OperationStatus(self.status)

    def to_dict(self, include_logs: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "reference": self.reference,
            "operation_type": self.operation_type,
            "status": self.status,
            "is_terminal": self.status_enum.is_terminal,
            "application_id": self.application_id,
            "application_code": self.application.code if self.application else None,
            "target_id": self.target_id,
            "target_name": self.target.name if self.target else None,
            "environment": self.environment_code,
            "deployment_id": self.deployment_id,
            "requested_by": self.requested_by.username if self.requested_by else None,
            "reason": self.reason,
            "request_id": self.request_id,
            "job_id": self.job_id,
            "parameters": self.parameters or {},
            "result": self.result or {},
            "result_code": self.result_code,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_logs:
            data["logs"] = [log.to_dict() for log in self.logs]
        return data


class OperationLog(PkMixin, Base):
    """Structured log line / command record produced during an operation."""

    __tablename__ = "operation_logs"
    __table_args__ = (Index("ix_operation_logs_operation_id", "operation_id"),)

    operation_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_operations.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    level: Mapped[str] = mapped_column(String(8), default="INFO", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    command: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    operation: Mapped[LifecycleOperation] = relationship(back_populates="logs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "message": self.message,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration_seconds,
        }


class HealthCheck(PkMixin, Base):
    """Result of one health check execution."""

    __tablename__ = "health_checks"
    __table_args__ = (
        Index("ix_health_checks_instance_id", "instance_id"),
        Index("ix_health_checks_checked_at", "checked_at"),
    )

    instance_id: Mapped[int] = mapped_column(
        ForeignKey("application_instances.id", ondelete="CASCADE"), nullable=False
    )
    check_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=HealthStatus.UNKNOWN.value, nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("lifecycle_operations.id", ondelete="SET NULL"), nullable=True
    )
    deployment_id: Mapped[int | None] = mapped_column(
        ForeignKey("deployments.id", ondelete="SET NULL"), nullable=True
    )

    instance = relationship("ApplicationInstance")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "instance_id": self.instance_id,
            "check_type": self.check_type,
            "status": self.status,
            "checked_at": self.checked_at.isoformat(),
            "duration_seconds": self.duration_seconds,
            "attempts": self.attempts,
            "message": self.message,
            "details": self.details or {},
        }


class DistributedLock(PkMixin, Base):
    """Database-backed lock used when Redis is unavailable (tests, degraded mode)."""

    __tablename__ = "distributed_locks"

    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    released: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
