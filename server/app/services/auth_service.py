"""Authentication service — login, token management, logout."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    decode_token,
)

from app.auth.password import verify_password, needs_rehash, hash_password
from app.extensions import db
from app.middleware.audit_middleware import record_audit
from app.models.token_blocklist import TokenBlocklist
from app.repositories.user_repo import UserRepository

log = structlog.get_logger(__name__)

_MAX_FAILED = 5
_LOCKOUT_MINUTES = 15


class AuthService:
    def __init__(self) -> None:
        self._user_repo = UserRepository()

    def login(self, email: str, password: str) -> dict:
        user = self._user_repo.get_by_email(email)
        if not user:
            log.warning("login_failed_unknown_email", email=email)
            raise ValueError("Invalid credentials")

        if not user.is_active:
            raise ValueError("Account is disabled")

        if user.is_locked():
            raise ValueError("Account is temporarily locked due to too many failed attempts")

        if not verify_password(password, user.password_hash):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= _MAX_FAILED:
                from datetime import timedelta
                user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=_LOCKOUT_MINUTES)
                log.warning("account_locked", user_id=user.id)
            db.session.flush()
            raise ValueError("Invalid credentials")

        # Successful login
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = datetime.now(timezone.utc)

        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)

        db.session.flush()

        identity = user.id
        additional_claims = {
            "tenant_id": user.tenant_id,
            "is_superadmin": user.is_superadmin,
            "roles": [r.name for r in user.roles],
        }

        access_token = create_access_token(identity=identity, additional_claims=additional_claims)
        refresh_token = create_refresh_token(identity=identity, additional_claims=additional_claims)

        record_audit("user.login", resource_type="user", resource_id=user.id)
        db.session.commit()

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": user.to_dict(),
        }

    def refresh(self, identity: str, claims: dict) -> dict:
        additional_claims = {k: v for k, v in claims.items() if k not in ("sub", "iat", "exp", "jti", "type")}
        access_token = create_access_token(identity=identity, additional_claims=additional_claims)
        return {"access_token": access_token}

    def logout(self, jti: str, token_type: str, expires_at: datetime, user_id: str | None) -> None:
        block = TokenBlocklist(
            jti=jti,
            token_type=token_type,
            expires_at=expires_at,
            user_id=user_id,
        )
        db.session.add(block)
        record_audit("user.logout", resource_type="user", resource_id=user_id)
        db.session.commit()
        log.info("token_revoked", jti=jti, user_id=user_id)
