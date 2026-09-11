"""Users, roles, permissions and API tokens."""

from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin, TimestampMixin


class Permission(PkMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    roles: Mapped[list[Role]] = relationship(
        secondary="role_permissions", back_populates="permissions", viewonly=True
    )


class Role(PkMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    permissions: Mapped[list[Permission]] = relationship(
        secondary="role_permissions", back_populates="roles"
    )
    users: Mapped[list[User]] = relationship(
        secondary="user_roles", back_populates="roles", viewonly=True
    )

    def permission_codes(self) -> set[str]:
        return {p.code for p in self.permissions}


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class User(PkMixin, TimestampMixin, UserMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Incremented on password change / logout-all to invalidate existing sessions.
    session_generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    roles: Mapped[list[Role]] = relationship(secondary="user_roles", back_populates="users")
    api_tokens: Mapped[list[ApiToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    # --- flask-login ---------------------------------------------------------
    def get_id(self) -> str:  # type: ignore[override]
        return f"{self.id}:{self.session_generation}"

    @property
    def is_locked(self) -> bool:
        from app.utils.time import utcnow

        return self.locked_until is not None and self.locked_until > utcnow()

    # --- RBAC -------------------------------------------------------------------
    @property
    def permission_codes(self) -> set[str]:
        codes: set[str] = set()
        for role in self.roles:
            codes |= role.permission_codes()
        return codes

    @property
    def role_names(self) -> list[str]:
        return sorted(r.name for r in self.roles)

    def has_permission(self, code: str) -> bool:
        return code in self.permission_codes

    def has_role(self, name: str) -> bool:
        return any(r.name == name for r in self.roles)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "roles": self.role_names,
            "must_change_password": self.must_change_password,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ApiToken(PkMixin, TimestampMixin, Base):
    """Personal API token. Only the SHA-256 hash of the secret is stored."""

    __tablename__ = "api_tokens"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_api_tokens_user_name"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    user: Mapped[User] = relationship(back_populates="api_tokens")

    @property
    def is_valid(self) -> bool:
        from app.utils.time import utcnow

        if self.revoked:
            return False
        return self.expires_at is None or self.expires_at > utcnow()
