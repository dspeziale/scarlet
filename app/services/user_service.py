"""User, role and API token management; RBAC seeding."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from flask import current_app

from app.audit import audit
from app.errors import ConflictError, NotFoundError, ValidationError
from app.extensions import db
from app.models.user import ApiToken, Permission, Role, User
from app.repositories import RoleRepository, UserRepository
from app.security.auth import generate_api_token
from app.security.passwords import hash_password, validate_password_policy
from app.security.rbac import DEFAULT_ROLES, PERMISSIONS, ROLE_ADMIN
from app.utils.time import utcnow

USERNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,63}$")


class UserService:
    def __init__(self) -> None:
        self.users = UserRepository()
        self.roles = RoleRepository()

    # --- RBAC seed -------------------------------------------------------------------------
    def sync_permissions_and_roles(self) -> None:
        """Idempotently create the permission catalogue and system roles."""
        existing = {p.code: p for p in db.session.execute(db.select(Permission)).scalars()}
        for code, description in PERMISSIONS.items():
            perm = existing.get(code)
            if perm is None:
                perm = Permission(code=code, description=description)
                db.session.add(perm)
                existing[code] = perm
            else:
                perm.description = description
        db.session.flush()
        for name, spec in DEFAULT_ROLES.items():
            role = self.roles.by_name(name)
            if role is None:
                role = Role(name=name, description=spec["description"], is_system=True)
                db.session.add(role)
                db.session.flush()
            role.description = spec["description"]
            role.is_system = True
            role.permissions = [existing[c] for c in sorted(spec["permissions"])]
        db.session.commit()

    # --- users -----------------------------------------------------------------------------
    def create_user(self, *, username: str, password: str, roles: list[str], email: str | None = None, full_name: str = "", must_change_password: bool = True, actor=None) -> User:
        username = (username or "").strip()
        if not USERNAME_RE.match(username):
            raise ValidationError("Invalid username.", errors={"username": ["3-64 characters: letters, digits, dot, dash, underscore."]})
        if self.users.by_username(username):
            raise ConflictError("Username already exists.")
        email = self._validate_email(email)
        if email and self.users.by_email(email):
            raise ConflictError("E-mail already in use.")
        validate_password_policy(password, min_length=int(current_app.config.get("SCARLET_PASSWORD_MIN_LENGTH", 12)), require_complexity=bool(current_app.config.get("SCARLET_PASSWORD_REQUIRE_COMPLEXITY", True)), username=username)
        user = User(username=username, email=email, full_name=(full_name or "")[:128], password_hash=hash_password(password), must_change_password=must_change_password, password_changed_at=utcnow())
        user.roles = self._resolve_roles(roles)
        db.session.add(user)
        db.session.commit()
        audit.record("USER_CREATED", user=actor, entity_type="User", entity_id=user.id, details={"username": username, "roles": user.role_names})
        return user

    def update_user(self, user: User, *, actor=None, **changes: Any) -> User:
        before = user.to_dict()
        if "email" in changes:
            email = self._validate_email(changes["email"])
            if email and email != user.email and self.users.by_email(email):
                raise ConflictError("E-mail already in use.")
            user.email = email
        if "full_name" in changes and changes["full_name"] is not None:
            user.full_name = str(changes["full_name"])[:128]
        if "is_active" in changes and changes["is_active"] is not None:
            if actor is not None and actor.id == user.id and not changes["is_active"]:
                raise ValidationError("You cannot deactivate your own account.")
            user.is_active = bool(changes["is_active"])
            if not user.is_active:
                user.session_generation += 1
        if "roles" in changes and changes["roles"] is not None:
            new_roles = self._resolve_roles(changes["roles"])
            if actor is not None and actor.id == user.id and not any(r.name == ROLE_ADMIN for r in new_roles) and user.has_role(ROLE_ADMIN):
                raise ValidationError("You cannot remove your own ADMIN role.")
            user.roles = new_roles
        if "must_change_password" in changes and changes["must_change_password"] is not None:
            user.must_change_password = bool(changes["must_change_password"])
        if changes.get("unlock"):
            user.locked_until = None
            user.failed_login_count = 0
        db.session.commit()
        audit.record("USER_UPDATED", user=actor, entity_type="User", entity_id=user.id, details={"before": {k: before[k] for k in ("email", "full_name", "is_active", "roles")}, "after": {k: user.to_dict()[k] for k in ("email", "full_name", "is_active", "roles")}})
        return user

    def delete_user(self, user: User, *, actor=None) -> None:
        if actor is not None and actor.id == user.id:
            raise ValidationError("You cannot delete your own account.")
        admins = [u for u in self.users.all() if u.has_role(ROLE_ADMIN) and u.is_active]
        if user.has_role(ROLE_ADMIN) and len(admins) <= 1:
            raise ValidationError("Cannot delete the last active administrator.")
        username = user.username
        db.session.delete(user)
        db.session.commit()
        audit.record("USER_DELETED", user=actor, entity_type="User", entity_id=user.id, details={"username": username})

    def _resolve_roles(self, names: list[str]) -> list[Role]:
        roles = []
        for name in names or []:
            role = self.roles.by_name(str(name).upper())
            if role is None:
                raise ValidationError(f"Unknown role {name}.", errors={"roles": [f"Unknown role {name}"]})
            roles.append(role)
        if not roles:
            raise ValidationError("At least one role is required.", errors={"roles": ["Required."]})
        return roles

    @staticmethod
    def _validate_email(email: str | None) -> str | None:
        email = (email or "").strip().lower()
        if not email:
            return None
        if len(email) > 255 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValidationError("Invalid e-mail address.", errors={"email": ["Invalid e-mail."]})
        return email

    # --- roles -------------------------------------------------------------------------------
    def create_role(self, *, name: str, description: str, permissions: list[str], actor=None) -> Role:
        name = (name or "").strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", name):
            raise ValidationError("Invalid role name.", errors={"name": ["Uppercase letters, digits and underscores."]})
        if self.roles.by_name(name):
            raise ConflictError("Role already exists.")
        role = Role(name=name, description=(description or "")[:255], is_system=False)
        role.permissions = self._resolve_permissions(permissions)
        db.session.add(role)
        db.session.commit()
        audit.record("ROLE_CREATED", user=actor, entity_type="Role", entity_id=role.id, details={"name": name, "permissions": sorted(role.permission_codes())})
        return role

    def update_role(self, role: Role, *, description: str | None = None, permissions: list[str] | None = None, actor=None) -> Role:
        if role.is_system and role.name == ROLE_ADMIN:
            raise ValidationError("The ADMIN role cannot be modified.")
        if description is not None:
            role.description = description[:255]
        if permissions is not None:
            role.permissions = self._resolve_permissions(permissions)
        db.session.commit()
        audit.record("ROLE_UPDATED", user=actor, entity_type="Role", entity_id=role.id, details={"name": role.name, "permissions": sorted(role.permission_codes())})
        return role

    def delete_role(self, role: Role, *, actor=None) -> None:
        if role.is_system:
            raise ValidationError("System roles cannot be deleted.")
        if role.users:
            raise ConflictError("Role is still assigned to users.")
        db.session.delete(role)
        db.session.commit()
        audit.record("ROLE_DELETED", user=actor, entity_type="Role", entity_id=role.id, details={"name": role.name})

    def _resolve_permissions(self, codes: list[str]) -> list[Permission]:
        perms = []
        for code in codes or []:
            if code not in PERMISSIONS:
                raise ValidationError(f"Unknown permission {code}.", errors={"permissions": [f"Unknown permission {code}"]})
            perm = db.session.execute(db.select(Permission).where(Permission.code == code)).scalar_one_or_none()
            if perm is not None:
                perms.append(perm)
        return perms

    # --- API tokens -----------------------------------------------------------------------------
    def create_token(self, user: User, *, name: str, expires_days: int | None = 90, description: str = "", actor=None) -> tuple[ApiToken, str]:
        name = (name or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}", name):
            raise ValidationError("Invalid token name.", errors={"name": ["1-64 characters."]})
        if any(t.name == name and not t.revoked for t in user.api_tokens):
            raise ConflictError("A token with this name already exists.")
        plaintext, token_hash, prefix = generate_api_token()
        token = ApiToken(user_id=user.id, name=name, token_hash=token_hash, token_prefix=prefix, description=description[:500], expires_at=(utcnow() + timedelta(days=int(expires_days))) if expires_days else None)
        db.session.add(token)
        db.session.commit()
        audit.record("API_TOKEN_CREATED", user=actor or user, entity_type="ApiToken", entity_id=token.id, details={"name": name, "token_prefix": prefix, "expires_at": token.expires_at.isoformat() if token.expires_at else None})
        return token, plaintext

    def revoke_token(self, user: User, token_id: int, *, actor=None) -> None:
        token = db.session.get(ApiToken, token_id)
        if token is None or token.user_id != user.id:
            raise NotFoundError("Token not found.")
        token.revoked = True
        db.session.commit()
        audit.record("API_TOKEN_REVOKED", user=actor or user, entity_type="ApiToken", entity_id=token.id, details={"name": token.name})
