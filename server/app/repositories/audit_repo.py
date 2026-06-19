"""Audit log repository — read-only queries only."""

from sqlalchemy import select

from app.extensions import db
from app.models.audit import AuditLog
from app.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLog]):
    model = AuditLog

    def list_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(db.session.execute(stmt).scalars())

    def list_global(self, limit: int = 200, offset: int = 0) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(db.session.execute(stmt).scalars())

    def list_by_user(self, user_id: str, limit: int = 100) -> list[AuditLog]:
        stmt = (
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        return list(db.session.execute(stmt).scalars())

    def save(self, obj):
        raise NotImplementedError("Use audit_middleware.record_audit() instead.")

    def delete(self, obj):
        raise NotImplementedError("AuditLog is immutable.")
