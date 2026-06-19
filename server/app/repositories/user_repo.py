"""User repository."""

from sqlalchemy import select

from app.extensions import db
from app.models.user import User, Role
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        return db.session.execute(stmt).scalar_one_or_none()

    def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        return db.session.execute(stmt).scalar_one_or_none()

    def list_by_tenant(self, tenant_id: str, limit: int = 100, offset: int = 0) -> list[User]:
        stmt = (
            select(User)
            .where(User.tenant_id == tenant_id)
            .limit(limit)
            .offset(offset)
        )
        return list(db.session.execute(stmt).scalars())


class RoleRepository(BaseRepository[Role]):
    model = Role

    def get_by_name(self, name: str) -> Role | None:
        stmt = select(Role).where(Role.name == name)
        return db.session.execute(stmt).scalar_one_or_none()

    def list_all(self, limit: int = 100, offset: int = 0) -> list[Role]:
        stmt = select(Role).limit(limit).offset(offset)
        return list(db.session.execute(stmt).scalars())
