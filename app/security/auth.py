"""Session and API-token authentication helpers."""

from __future__ import annotations

import hashlib
import secrets

from flask import Flask, g, request

from app.extensions import db, login_manager
from app.models.user import ApiToken, User
from app.utils.time import utcnow

TOKEN_PREFIX = "scl_"


def generate_api_token() -> tuple[str, str, str]:
    """Return (plaintext_token, sha256_hash, display_prefix)."""
    secret = secrets.token_urlsafe(32)
    plaintext = f"{TOKEN_PREFIX}{secret}"
    return plaintext, hash_token(plaintext), plaintext[:12]


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def register_auth(app: Flask) -> None:
    login_manager.init_app(app)
    login_manager.login_view = "web_auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "warning"
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def load_user(composite_id: str) -> User | None:
        try:
            raw_id, _, raw_gen = composite_id.partition(":")
            user_id = int(raw_id)
            generation = int(raw_gen) if raw_gen else None
        except ValueError:
            return None
        user = db.session.get(User, user_id)
        if user is None or not user.is_active:
            return None
        if generation is not None and user.session_generation != generation:
            # password changed / logout everywhere -> session invalidated
            return None
        return user

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import jsonify, redirect, url_for

        if request.path.startswith("/api/"):
            return (
                jsonify(
                    {"ok": False, "error": {"code": "AUTHENTICATION_REQUIRED", "message": "Authentication required."}}
                ),
                401,
            )
        return redirect(url_for("web_auth.login", next=request.full_path))

    @app.before_request
    def _load_api_user() -> None:
        g.api_user = None
        g.api_token = None
        header = request.headers.get("Authorization", "")
        if not header.lower().startswith("bearer "):
            return
        plaintext = header[7:].strip()
        if not plaintext.startswith(TOKEN_PREFIX) or len(plaintext) > 128:
            return
        token = db.session.execute(
            db.select(ApiToken).where(ApiToken.token_hash == hash_token(plaintext))
        ).scalar_one_or_none()
        if token is None or not token.is_valid:
            return
        user = token.user
        if user is None or not user.is_active:
            return
        g.api_user = user
        g.api_token = token
        now = utcnow()
        if token.last_used_at is None or (now - token.last_used_at).total_seconds() > 60:
            token.last_used_at = now
            db.session.commit()
