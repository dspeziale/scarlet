"""Authentication endpoints."""

from __future__ import annotations

from flask import current_app, g

from app.api import api
from app.api.responses import json_body, ok
from app.errors import AuthenticationError, ValidationError
from app.extensions import limiter
from app.security.rbac import get_current_user, login_required_any
from app.services.auth_service import AuthService
from app.services.user_service import UserService


@api.post("/auth/login")
@limiter.limit(
    lambda: current_app.config.get("SCARLET_LOGIN_RATE_LIMIT", "5 per minute"),
    deduct_when=lambda resp: resp.status_code != 200,
)
def login():
    data = json_body()
    username = str(data.get("username", ""))[:64]
    password = str(data.get("password", ""))[:256]
    if not username or not password:
        raise ValidationError("username and password are required.")
    user = AuthService().authenticate(
        username, password, remember=bool(data.get("remember", False))
    )
    return ok({"user": user.to_dict(), "permissions": sorted(user.permission_codes)})


@api.post("/auth/logout")
@login_required_any
def logout():
    AuthService().logout(get_current_user())
    return ok({"logged_out": True})


@api.get("/auth/me")
@login_required_any
def me():
    user = get_current_user()
    return ok(
        {
            "user": user.to_dict(),
            "permissions": sorted(user.permission_codes),
            "auth": "token" if getattr(g, "api_token", None) else "session",
        }
    )


@api.post("/auth/password")
@login_required_any
def change_password():
    user = get_current_user()
    if getattr(g, "api_token", None):
        raise AuthenticationError("Password changes require an interactive session.")
    data = json_body()
    AuthService().change_password(
        user, str(data.get("current_password", "")), str(data.get("new_password", ""))
    )
    return ok({"changed": True})


@api.get("/auth/tokens")
@login_required_any
def list_tokens():
    user = get_current_user()
    return ok(
        [
            {
                "id": t.id,
                "name": t.name,
                "prefix": t.token_prefix,
                "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
                "revoked": t.revoked,
                "created_at": t.created_at.isoformat(),
            }
            for t in user.api_tokens
        ]
    )


@api.post("/auth/tokens")
@login_required_any
def create_token():
    user = get_current_user()
    if getattr(g, "api_token", None):
        raise AuthenticationError("Tokens can only be created from an interactive session.")
    data = json_body()
    expires = data.get("expires_days", 90)
    try:
        expires_days = int(expires) if expires not in (None, "", 0, "0") else None
    except ValueError as exc:
        raise ValidationError("expires_days must be an integer.") from exc
    if expires_days is not None and not 1 <= expires_days <= 730:
        raise ValidationError("expires_days must be between 1 and 730.")
    token, plaintext = UserService().create_token(
        user,
        name=str(data.get("name", "")),
        expires_days=expires_days,
        description=str(data.get("description", "")),
    )
    # the plaintext is returned exactly once
    return ok(
        {
            "id": token.id,
            "name": token.name,
            "token": plaintext,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
        },
        201,
    )


@api.delete("/auth/tokens/<int:token_id>")
@login_required_any
def revoke_token(token_id: int):
    user = get_current_user()
    UserService().revoke_token(user, token_id)
    return ok({"revoked": True})
