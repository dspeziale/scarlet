"""Authentication: login with lockout, logout, password change/reset."""

from __future__ import annotations

from datetime import timedelta

from flask import current_app, request, session
from flask_login import login_user, logout_user

from app.audit import audit
from app.errors import AuthenticationError, AuthorizationError, ValidationError
from app.extensions import db
from app.models.enums import AuditResult, SecurityEventSeverity
from app.models.user import User
from app.repositories import UserRepository
from app.security.passwords import hash_password, needs_rehash, validate_password_policy, verify_password
from app.utils.time import utcnow


class AuthService:
    def __init__(self) -> None:
        self.users = UserRepository()

    def authenticate(self, username: str, password: str, *, remember: bool = False) -> User:
        username = (username or "").strip()
        user = self.users.by_username(username) if username else None
        ip = request.remote_addr if request else None
        if user is None:
            # constant-time-ish: still hash to avoid trivial user enumeration by timing
            verify_password(hash_password("scarlet-dummy-password-000"), password or "")
            audit.record("USER_LOGIN", result=AuditResult.FAILURE, entity_type="User", details={"username": username, "reason": "unknown user"})
            raise AuthenticationError("Invalid username or password.")
        if not user.is_active:
            audit.record("USER_LOGIN", user=user, result=AuditResult.DENIED, entity_type="User", entity_id=user.id, details={"reason": "inactive"})
            raise AuthenticationError("Invalid username or password.")
        if user.is_locked:
            audit.record("USER_LOGIN", user=user, result=AuditResult.DENIED, entity_type="User", entity_id=user.id, details={"reason": "locked"})
            raise AuthenticationError("Account temporarily locked. Try again later.")
        if not verify_password(user.password_hash, password or ""):
            user.failed_login_count += 1
            max_failed = int(current_app.config.get("SCARLET_MAX_FAILED_LOGINS", 10))
            if user.failed_login_count >= max_failed:
                user.locked_until = utcnow() + timedelta(minutes=int(current_app.config.get("SCARLET_LOCKOUT_MINUTES", 15)))
                user.failed_login_count = 0
                audit.security_event("ACCOUNT_LOCKED", f"Account {user.username} locked after repeated failed logins.", severity=SecurityEventSeverity.HIGH, user=user, commit=False)
            db.session.commit()
            audit.record("USER_LOGIN", user=user, result=AuditResult.FAILURE, entity_type="User", entity_id=user.id, details={"reason": "bad password"})
            raise AuthenticationError("Invalid username or password.")
        # success
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = utcnow()
        user.last_login_ip = ip
        db.session.commit()
        session.clear()  # prevent session fixation
        login_user(user, remember=remember, fresh=True)
        session.permanent = True
        audit.record("USER_LOGIN", user=user, entity_type="User", entity_id=user.id)
        return user

    def logout(self, user: User | None) -> None:
        if user is not None and getattr(user, "is_authenticated", False):
            audit.record("USER_LOGOUT", user=user, entity_type="User", entity_id=user.id)
        logout_user()
        session.clear()

    def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(user.password_hash, current_password or ""):
            audit.record("PASSWORD_CHANGE", user=user, result=AuditResult.FAILURE, entity_type="User", entity_id=user.id, details={"reason": "wrong current password"})
            raise AuthorizationError("Current password is incorrect.")
        self._set_password(user, new_password)
        audit.record("PASSWORD_CHANGE", user=user, entity_type="User", entity_id=user.id)

    def admin_reset_password(self, admin: User, target: User, new_password: str, *, must_change: bool = True) -> None:
        self._set_password(target, new_password)
        target.must_change_password = must_change
        target.locked_until = None
        target.failed_login_count = 0
        db.session.commit()
        audit.record("PASSWORD_RESET", user=admin, entity_type="User", entity_id=target.id, details={"target_username": target.username})

    def _set_password(self, user: User, new_password: str) -> None:
        validate_password_policy(
            new_password,
            min_length=int(current_app.config.get("SCARLET_PASSWORD_MIN_LENGTH", 12)),
            require_complexity=bool(current_app.config.get("SCARLET_PASSWORD_REQUIRE_COMPLEXITY", True)),
            username=user.username,
        )
        if verify_password(user.password_hash, new_password):
            raise ValidationError("New password must differ from the current one.", errors={"password": ["Must differ from current password."]})
        user.password_hash = hash_password(new_password)
        user.password_changed_at = utcnow()
        user.must_change_password = False
        user.session_generation += 1  # invalidate other sessions
        db.session.commit()
