"""Generic repository base with automatic tenant filtering."""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import select

from app.extensions import db
from app.tenants.context import get_tenant_id

T = TypeVar("T")


class BaseRepository(Generic[T]):
    model: type[T]

    def _tenant_filter(self, stmt):
        tid = get_tenant_id()
        if tid and hasattr(self.model, "tenant_id"):
            stmt = stmt.where(self.model.tenant_id == tid)  # type: ignore[attr-defined]
        return stmt

    def get_by_id(self, record_id: str) -> T | None:
        stmt = self._tenant_filter(select(self.model).where(self.model.id == record_id))  # type: ignore[attr-defined]
        return db.session.execute(stmt).scalar_one_or_none()

    def list_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        stmt = self._tenant_filter(select(self.model)).limit(limit).offset(offset)  # type: ignore[attr-defined]
        return list(db.session.execute(stmt).scalars())

    def save(self, obj: T) -> T:
        db.session.add(obj)
        db.session.flush()
        return obj

    def delete(self, obj: T) -> None:
        db.session.delete(obj)
        db.session.flush()

    def count(self) -> int:
        from sqlalchemy import func
        stmt = self._tenant_filter(select(func.count()).select_from(self.model))  # type: ignore[attr-defined]
        return db.session.execute(stmt).scalar_one()
