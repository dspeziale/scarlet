"""Task, TaskAssignment, TaskResult models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

TASK_TYPES = [
    "network_discovery",
    "service_detection",
    "os_fingerprinting",
    "snmp_inventory",
    "wifi_scan",
    "ble_scan",
    "custom_script",
    "ping",
    "traffic_capture",
    # IDS / Suricata control (dispatched from the server console)
    "ids_start",
    "ids_stop",
    "ids_restart",
    "ids_status",
    "ids_rule_deploy",
    "config_update",
    "pcap_start",
    "pcap_stop",
]

TASK_STATUSES = ["queued", "assigned", "running", "completed", "failed", "cancelled"]


def _now():
    return datetime.now(timezone.utc)


class Task(db.Model):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    priority: Mapped[int] = mapped_column(default=5, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    creator: Mapped["User"] = relationship("User", foreign_keys=[created_by])  # type: ignore[name-defined]
    assignments: Mapped[list["TaskAssignment"]] = relationship("TaskAssignment", back_populates="task")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "task_type": self.task_type,
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "status": self.status,
            "priority": self.priority,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "created_at": self.created_at.isoformat(),
        }


class TaskAssignment(db.Model):
    __tablename__ = "task_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="assigned", nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped["Task"] = relationship("Task", back_populates="assignments")
    probe: Mapped["Probe"] = relationship("Probe", back_populates="tasks")  # type: ignore[name-defined]
    result: Mapped["TaskResult | None"] = relationship("TaskResult", back_populates="assignment", uselist=False)


class TaskResult(db.Model):
    __tablename__ = "task_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    assignment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("task_assignments.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id"), nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_data: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float | None] = mapped_column()
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    assignment: Mapped["TaskAssignment"] = relationship("TaskAssignment", back_populates="result")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "assignment_id": self.assignment_id,
            "task_id": self.task_id,
            "probe_id": self.probe_id,
            "status": self.status,
            "result_data": self.result_data,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
            "received_at": self.received_at.isoformat(),
        }
