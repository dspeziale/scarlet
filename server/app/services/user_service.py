"""User management service."""

from __future__ import annotations

import structlog

from app.auth.password import hash_password
from app.extensions import db
from app.middleware.audit_middleware import record_audit
from app.models.user import User, Role
from app.repositories.user_repo import UserRepository, RoleRepository

log = structlog.get_logger(__name__)


class UserService:
    def __init__(self) -> None:
        self._user_repo = UserRepository()
        self._role_repo = RoleRepository()

    def create_user(
        self,
        email: str,
        username: str,
        password: str,
        tenant_id: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        role_names: list[str] | None = None,
        is_superadmin: bool = False,
    ) -> User:
        if self._user_repo.get_by_email(email):
            raise ValueError(f"Email '{email}' is already registered")
        if self._user_repo.get_by_username(username):
            raise ValueError(f"Username '{username}' is already taken")

        user = User(
            email=email,
            username=username,
            password_hash=hash_password(password),
            tenant_id=tenant_id,
            first_name=first_name,
            last_name=last_name,
            is_superadmin=is_superadmin,
        )

        if role_names:
            for rname in role_names:
                role = self._role_repo.get_by_name(rname)
                if role:
                    user.roles.append(role)

        db.session.add(user)
        record_audit(
            "user.create",
            resource_type="user",
            resource_id=user.id,
            payload={"email": email, "username": username, "roles": role_names},
        )
        db.session.commit()
        log.info("user_created", user_id=user.id, email=email)
        return user

    def update_user(self, user_id: str, calling_user: User, **kwargs) -> User:
        user = self._user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User not found")

        # Non-superadmin can only edit within their tenant
        if not calling_user.is_superadmin and user.tenant_id != calling_user.tenant_id:
            raise PermissionError("Cannot edit users from another tenant")

        if "password" in kwargs:
            user.password_hash = hash_password(kwargs.pop("password"))

        allowed_fields = {"first_name", "last_name", "is_active", "email"}
        for k, v in kwargs.items():
            if k in allowed_fields:
                setattr(user, k, v)

        record_audit("user.update", resource_type="user", resource_id=user_id, payload=kwargs)
        db.session.commit()
        return user

    def assign_role(self, user_id: str, role_name: str) -> User:
        user = self._user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        role = self._role_repo.get_by_name(role_name)
        if not role:
            raise ValueError(f"Role '{role_name}' not found")
        if not user.has_role(role_name):
            user.roles.append(role)
        record_audit("user.assign_role", resource_type="user", resource_id=user_id, payload={"role": role_name})
        db.session.commit()
        return user

    def get_user(self, user_id: str) -> User:
        user = self._user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        return user

    def list_users(self, tenant_id: str, limit: int = 100, offset: int = 0) -> list[User]:
        return self._user_repo.list_by_tenant(tenant_id, limit=limit, offset=offset)
