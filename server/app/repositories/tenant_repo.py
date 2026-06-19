"""Tenant repository."""

from sqlalchemy import select

from app.extensions import db
from app.models.tenant import Tenant
from app.repositories.base import BaseRepository


class TenantRepository(BaseRepository[Tenant]):
    model = Tenant

    def get_by_id(self, record_id: str) -> Tenant | None:
        # Tenants are NOT filtered by tenant_id (they are the root)
        return db.session.get(Tenant, record_id)

    def list_all(self, limit: int = 100, offset: int = 0) -> list[Tenant]:
        stmt = select(Tenant).where(Tenant.is_active == True).limit(limit).offset(offset)
        return list(db.session.execute(stmt).scalars())

    def get_by_slug(self, slug: str) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.slug == slug)
        return db.session.execute(stmt).scalar_one_or_none()

    def get_by_name(self, name: str) -> Tenant | None:
        stmt = select(Tenant).where(Tenant.name == name)
        return db.session.execute(stmt).scalar_one_or_none()
