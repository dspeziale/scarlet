"""Authentication, own profile and sessions."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ..context import AppContext
from ..errors import RateLimited, Unauthorized
from ..security.rbac import permissions_for
from ..security.users import LoginResult, Session
from .deps import Audited, audited, client_ip, cookie_name, current_session, get_ctx

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ProfileBody(BaseModel):
    language: Literal["it", "en"] | None = None
    display_name: str | None = Field(None, max_length=120)


def session_payload(session: Session) -> dict[str, Any]:
    return {"user": session.user.public(), "permissions": permissions_for(session.user.role),
            "csrfToken": session.csrf_token, "expiresAt": session.expires_at}  # fmt: skip


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, ctx: AppContext = Depends(get_ctx),
          audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ip = client_ip(request, ctx)
    for key in (f"ip:{ip}", f"user:{body.username.lower()}"):
        if not ctx.login_limiter.hit(key):
            audit("auth.login", result="denied", detail={"username": body.username, "reason": "rate_limited"})
            raise RateLimited("too many login attempts, retry later",
                              params={"retryAfter": ctx.login_limiter.retry_after(key)})  # fmt: skip
    result, user = ctx.users.authenticate(body.username, body.password)
    if result != LoginResult.OK or user is None:
        from ..audit import AuditContext

        ctx.audit.record(AuditContext(user.id if user else None, body.username[:64], ip,
                                      request.headers.get("user-agent", "")),
                         "auth.login", result="failure", detail={"reason": result})  # fmt: skip
        # Same message for unknown user and wrong password; lockout/disabled are disclosed
        # only after a correct password would not have helped anyway.
        params = {"reason": result if result in (LoginResult.LOCKED,) else "invalid"}
        raise Unauthorized("invalid username or password", params=params)
    token, session = ctx.users.create_session(user, ip, request.headers.get("user-agent", ""))
    request.state.session = session
    response.set_cookie(cookie_name(ctx), token, httponly=True, secure=ctx.settings.cookie_secure,
                        samesite="strict", path="/", max_age=ctx.settings.auth.session_absolute_hours * 3600)  # fmt: skip
    audit("auth.login")
    return session_payload(session)


@router.post("/logout")
def logout(request: Request, response: Response, session: Session = Depends(current_session),
           ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ctx.users.delete_session(session.id)
    response.delete_cookie(cookie_name(ctx), path="/", secure=ctx.settings.cookie_secure, httponly=True,
                           samesite="strict")  # fmt: skip
    audit("auth.logout")
    return {"ok": True}


@router.get("/me")
def me(session: Session = Depends(current_session)) -> dict[str, Any]:
    return session_payload(session)


@router.patch("/me")
def update_profile(body: ProfileBody, session: Session = Depends(current_session),
                   ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    user = ctx.users.update(session.user.id, actor_id=session.user.id, language=body.language,
                            display_name=body.display_name)  # fmt: skip
    return {"user": user.public()}


@router.post("/change-password")
def change_password(body: ChangePasswordBody, request: Request, response: Response,
                    session: Session = Depends(current_session), ctx: AppContext = Depends(get_ctx),
                    audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    try:
        ctx.users.change_own_password(session.user.id, body.current_password, body.new_password)
    except Exception:
        audit("auth.password_change", result="failure")
        raise
    # All sessions were revoked: open a fresh one for the current browser.
    user = ctx.users.get(session.user.id)
    token, new_session = ctx.users.create_session(user, client_ip(request, ctx), request.headers.get("user-agent", ""))
    response.set_cookie(cookie_name(ctx), token, httponly=True, secure=ctx.settings.cookie_secure,
                        samesite="strict", path="/", max_age=ctx.settings.auth.session_absolute_hours * 3600)  # fmt: skip
    audit("auth.password_change")
    return session_payload(new_session)


@router.get("/sessions")
def my_sessions(session: Session = Depends(current_session), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    items = ctx.users.list_sessions(session.user.id)
    for it in items:
        it["current"] = it["id"] == session.ref
    return {"items": items}


@router.post("/sessions/revoke-others")
def revoke_others(session: Session = Depends(current_session), ctx: AppContext = Depends(get_ctx),
                  audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    n = ctx.users.revoke_user_sessions(session.user.id, except_session=session.id)
    audit("auth.sessions_revoked", detail={"count": n})
    return {"revoked": n}
