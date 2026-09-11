"""Deployments, deployment steps and approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin, TimestampMixin
from app.models.enums import (
    ApprovalStatus,
    DeploymentKind,
    DeploymentStatus,
    DeploymentStrategy,
    StepStatus,
)


class DeploymentBatch(PkMixin, TimestampMixin, Base):
    """Groups deployments of one version to multiple hosts (multi-host deployment)."""

    __tablename__ = "deployment_batches"

    reference: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("application_versions.id", ondelete="RESTRICT"), nullable=False
    )
    strategy: Mapped[str] = mapped_column(
        String(16), default=DeploymentStrategy.SEQUENTIAL.value, nullable=False
    )
    max_parallel: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    stop_on_failure: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)

    deployments: Mapped[list[Deployment]] = relationship(back_populates="batch")
    application = relationship("Application")
    version = relationship("ApplicationVersion")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "reference": self.reference,
            "application_id": self.application_id,
            "version_id": self.version_id,
            "strategy": self.strategy,
            "max_parallel": self.max_parallel,
            "stop_on_failure": self.stop_on_failure,
            "deployment_ids": [d.id for d in self.deployments],
            "statuses": {d.id: d.status for d in self.deployments},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Deployment(PkMixin, TimestampMixin, Base):
    __tablename__ = "deployments"
    __table_args__ = (
        Index("ix_deployments_target_id", "target_id"),
        Index("ix_deployments_application_id", "application_id"),
        Index("ix_deployments_created_at", "created_at"),
        Index("ix_deployments_status", "status"),
    )

    reference: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default=DeploymentKind.DEPLOY.value, nullable=False)
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("deployment_batches.id", ondelete="SET NULL"), nullable=True
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="RESTRICT"), nullable=False
    )
    version_id: Mapped[int] = mapped_column(
        ForeignKey("application_versions.id", ondelete="RESTRICT"), nullable=False
    )
    previous_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_versions.id", ondelete="SET NULL"), nullable=True
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("target_hosts.id", ondelete="RESTRICT"), nullable=False
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False
    )
    instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_instances.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24), default=DeploymentStatus.CREATED.value, nullable=False
    )
    strategy: Mapped[str] = mapped_column(
        String(16), default=DeploymentStrategy.SEQUENTIAL.value, nullable=False
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    auto_rollback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rollback_of_id: Mapped[int | None] = mapped_column(
        ForeignKey("deployments.id", ondelete="SET NULL"), nullable=True
    )
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    preflight_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    application = relationship("Application")
    version = relationship("ApplicationVersion", foreign_keys=[version_id])
    previous_version = relationship("ApplicationVersion", foreign_keys=[previous_version_id])
    target = relationship("TargetHost")
    environment = relationship("Environment")
    instance = relationship("ApplicationInstance", foreign_keys=[instance_id])
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    batch: Mapped[DeploymentBatch | None] = relationship(back_populates="deployments")
    steps: Mapped[list[DeploymentStep]] = relationship(
        back_populates="deployment", cascade="all, delete-orphan", order_by="DeploymentStep.sequence"
    )
    approvals: Mapped[list[DeploymentApproval]] = relationship(
        back_populates="deployment", cascade="all, delete-orphan"
    )

    @property
    def status_enum(self) -> DeploymentStatus:
        return DeploymentStatus(self.status)

    @property
    def is_terminal(self) -> bool:
        return self.status_enum.is_terminal

    def to_dict(self, include_steps: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "reference": self.reference,
            "kind": self.kind,
            "batch_id": self.batch_id,
            "batch_reference": self.batch.reference if self.batch else None,
            "application_id": self.application_id,
            "application_code": self.application.code if self.application else None,
            "application_name": self.application.name if self.application else None,
            "version_id": self.version_id,
            "version": self.version.version if self.version else None,
            "previous_version": self.previous_version.version if self.previous_version else None,
            "target_id": self.target_id,
            "target_name": self.target.name if self.target else None,
            "environment": self.environment.code if self.environment else None,
            "is_production": bool(self.environment and self.environment.is_production),
            "runtime_type": self.target.runtime_type if self.target else None,
            "status": self.status,
            "status_summary": self.status_enum.summary,
            "is_terminal": self.is_terminal,
            "strategy": self.strategy,
            "requested_by": self.requested_by.username if self.requested_by else None,
            "reason": self.reason,
            "request_id": self.request_id,
            "job_id": self.job_id,
            "auto_rollback": self.auto_rollback,
            "rollback_of_id": self.rollback_of_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "preflight_result": self.preflight_result,
            "result_summary": self.result_summary,
            "queued_at": self.queued_at.isoformat() if self.queued_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "approvals": [a.to_dict() for a in self.approvals],
        }
        if include_steps:
            data["steps"] = [s.to_dict() for s in self.steps]
            data["plan"] = self.plan
        return data


class DeploymentStep(PkMixin, Base):
    __tablename__ = "deployment_steps"
    __table_args__ = (Index("ix_deployment_steps_deployment_id", "deployment_id"),)

    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("deployments.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=StepStatus.PENDING.value, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    deployment: Mapped[Deployment] = relationship(back_populates="steps")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sequence": self.sequence,
            "name": self.name,
            "label": self.label,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "error_message": self.error_message,
            "details": self.details or {},
        }


class DeploymentApproval(PkMixin, TimestampMixin, Base):
    """Approval record for production deployments (second-person approval)."""

    __tablename__ = "deployment_approvals"

    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("deployments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ApprovalStatus.PENDING.value, nullable=False
    )
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    deployment: Mapped[Deployment] = relationship(back_populates="approvals")
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    decided_by = relationship("User", foreign_keys=[decided_by_id])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "requested_by": self.requested_by.username if self.requested_by else None,
            "decided_by": self.decided_by.username if self.decided_by else None,
            "comment": self.comment,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
