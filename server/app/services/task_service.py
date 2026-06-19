"""Task scheduling and result processing service."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.extensions import db
from app.middleware.audit_middleware import record_audit
from app.models.task import Task, TaskAssignment, TaskResult, TASK_TYPES
from app.repositories.task_repo import TaskRepository, TaskResultRepository

log = structlog.get_logger(__name__)


class TaskService:
    def __init__(self) -> None:
        self._task_repo = TaskRepository()
        self._result_repo = TaskResultRepository()

    def create_task(
        self,
        tenant_id: str,
        created_by: str,
        task_type: str,
        parameters: dict | None = None,
        name: str | None = None,
        description: str | None = None,
        priority: int = 5,
        scheduled_at: datetime | None = None,
    ) -> Task:
        if task_type not in TASK_TYPES:
            raise ValueError(f"Unknown task type '{task_type}'. Valid: {TASK_TYPES}")

        task = Task(
            tenant_id=tenant_id,
            created_by=created_by,
            task_type=task_type,
            parameters=parameters or {},
            name=name,
            description=description,
            priority=priority,
            scheduled_at=scheduled_at,
            status="queued",
        )
        db.session.add(task)
        record_audit("task.create", resource_type="task", resource_id=task.id,
                     payload={"task_type": task_type})
        db.session.commit()
        log.info("task_created", task_id=task.id, task_type=task_type)
        return task

    def assign_task(self, task_id: str, probe_id: str, tenant_id: str) -> TaskAssignment:
        task = self._task_repo.get_by_id(task_id)
        if not task or task.tenant_id != tenant_id:
            raise ValueError("Task not found")
        if task.status not in ("queued",):
            raise ValueError(f"Task status '{task.status}' cannot be assigned")

        assignment = TaskAssignment(
            task_id=task_id,
            probe_id=probe_id,
            tenant_id=tenant_id,
            status="assigned",
        )
        task.status = "assigned"
        db.session.add(assignment)
        record_audit("task.assign", resource_type="task", resource_id=task_id,
                     payload={"probe_id": probe_id})
        db.session.commit()
        return assignment

    def get_pending_tasks(self, probe_id: str, tenant_id: str) -> list[TaskAssignment]:
        return self._task_repo.list_pending_for_probe(probe_id, tenant_id)

    def accept_task(self, assignment_id: str, probe_id: str) -> TaskAssignment:
        assignment = db.session.get(TaskAssignment, assignment_id)
        if not assignment or assignment.probe_id != probe_id:
            raise ValueError("Assignment not found")
        assignment.status = "running"
        assignment.accepted_at = datetime.now(timezone.utc)
        assignment.started_at = datetime.now(timezone.utc)
        assignment.task.status = "running"
        db.session.commit()
        return assignment

    def submit_result(
        self,
        assignment_id: str,
        probe_id: str,
        status: str,
        result_data: dict | None = None,
        error_message: str | None = None,
        duration_seconds: float | None = None,
    ) -> TaskResult:
        assignment = db.session.get(TaskAssignment, assignment_id)
        if not assignment or assignment.probe_id != probe_id:
            raise ValueError("Assignment not found")

        result = TaskResult(
            assignment_id=assignment_id,
            tenant_id=assignment.tenant_id,
            probe_id=probe_id,
            task_id=assignment.task_id,
            status=status,
            result_data=result_data,
            error_message=error_message,
            duration_seconds=duration_seconds,
        )
        assignment.status = status
        assignment.completed_at = datetime.now(timezone.utc)
        assignment.task.status = status

        db.session.add(result)
        record_audit("task.result_submitted", resource_type="task_result", resource_id=result.id,
                     payload={"status": status})
        db.session.commit()
        log.info("task_result_received", assignment_id=assignment_id, status=status)
        return result

    def cancel_task(self, task_id: str, tenant_id: str) -> Task:
        task = self._task_repo.get_by_id(task_id)
        if not task or task.tenant_id != tenant_id:
            raise ValueError("Task not found")
        if task.status in ("completed", "failed"):
            raise ValueError("Cannot cancel a finished task")
        task.status = "cancelled"
        record_audit("task.cancel", resource_type="task", resource_id=task_id)
        db.session.commit()
        return task

    def list_tasks(self, tenant_id: str, status: str | None = None) -> list[Task]:
        if status:
            return self._task_repo.list_by_status(status, tenant_id)
        from sqlalchemy import select
        stmt = select(Task).where(Task.tenant_id == tenant_id).order_by(Task.created_at.desc()).limit(200)
        return list(db.session.execute(stmt).scalars())
