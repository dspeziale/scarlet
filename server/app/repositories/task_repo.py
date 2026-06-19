"""Task repository."""

from sqlalchemy import select

from app.extensions import db
from app.models.task import Task, TaskAssignment, TaskResult
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    model = Task

    def list_by_status(self, status: str, tenant_id: str | None = None) -> list[Task]:
        stmt = select(Task).where(Task.status == status)
        if tenant_id:
            stmt = stmt.where(Task.tenant_id == tenant_id)
        return list(db.session.execute(stmt).scalars())

    def list_pending_for_probe(self, probe_id: str, tenant_id: str) -> list[TaskAssignment]:
        stmt = (
            select(TaskAssignment)
            .where(
                TaskAssignment.probe_id == probe_id,
                TaskAssignment.tenant_id == tenant_id,
                TaskAssignment.status.in_(["assigned", "queued"]),
            )
            .order_by(TaskAssignment.assigned_at)
        )
        return list(db.session.execute(stmt).scalars())


class TaskResultRepository(BaseRepository[TaskResult]):
    model = TaskResult

    def get_by_assignment(self, assignment_id: str) -> TaskResult | None:
        stmt = select(TaskResult).where(TaskResult.assignment_id == assignment_id)
        return db.session.execute(stmt).scalar_one_or_none()
