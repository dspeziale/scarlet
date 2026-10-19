"""FastAPI dependencies: context, authentication, CSRF, RBAC and audit context."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from typing import Any

from fastapi import Depends, Request

from ..audit import AuditContext
from ..context import AppContext
from ..errors import Forbidden, Unauthorized
from ..logging_setup import request_id_var
from ..security.rbac import Perm, has_perm
from ..security.users import Session, csrf_matches

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-CSRF-Token"


def cookie_name(ctx: AppContext) -> str:
    # The __Host- prefix forces Secure, Path=/ and no Domain in the browser.
    return "__Host-pkm_session" if ctx.settings.cookie_secure else "pkm_session"


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def client_ip(request: Request, ctx: AppContext | None = None) -> str:
    peer = request.client.host if request.client else ""
    ctx = ctx or request.app.state.ctx
    trusted = ctx.settings.server.trusted_proxies
    if peer and trusted and peer in trusted:
        fwd = request.headers.get("x-forwarded-for", "")
        candidate = fwd.split(",")[-1].strip() if fwd else ""
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            pass
    return peer


def _session(request: Request, ctx: AppContext) -> Session:
    cached = getattr(request.state, "session", None)
    if cached is not None:
        return cached
    token = request.cookies.get(cookie_name(ctx))
    session = ctx.users.resolve_session(token) if token else None
    if session is None:
        raise Unauthorized("authentication required")
    if request.method not in SAFE_METHODS:
        if not csrf_matches(session.csrf_token, request.headers.get(CSRF_HEADER)):
            raise Forbidden("missing or invalid CSRF token", params={"reason": "csrf"})
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host", "")
            if origin.split("://", 1)[-1] != host:
                raise Forbidden("cross-origin request rejected", params={"reason": "origin"})
    request.state.session = session
    return session


def current_session(request: Request, ctx: AppContext = Depends(get_ctx)) -> Session:
    session = _session(request, ctx)
    # A user who must change the password can only reach the auth endpoints.
    if session.user.must_change_password and not request.url.path.startswith("/api/v1/auth/"):
        raise Forbidden("password change required", params={"reason": "must_change_password"})
    return session


def require(perm: Perm) -> Callable[..., Session]:
    def dep(request: Request, session: Session = Depends(current_session),
            ctx: AppContext = Depends(get_ctx)) -> Session:  # fmt: skip
        if not has_perm(session.user.role, perm):
            ctx.audit.record(audit_ctx(request, session), "access.denied", result="denied",
                             detail={"permission": perm.value, "path": request.url.path})  # fmt: skip
            raise Forbidden("your role does not allow this operation",
                            params={"permission": perm.value, "role": session.user.role})  # fmt: skip
        return session

    return dep


def audit_ctx(request: Request, session: Session | None) -> AuditContext:
    return AuditContext(
        user_id=session.user.id if session else None,
        username=session.user.username if session else "anonymous",
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        session_ref=session.ref if session else "",
        request_id=request_id_var.get() or "",
    )


class Audited:
    """Helper bound to a request to record audit entries concisely."""

    def __init__(self, request: Request, ctx: AppContext) -> None:
        self.request = request
        self.ctx = ctx

    @property
    def session(self) -> Session | None:
        # Resolved lazily: the session dependency may run after this one.
        return getattr(self.request.state, "session", None)

    def __call__(self, action: str, *, result: str = "success", kind: str = "", name: str = "",
                 namespace: str | None = "", detail: dict[str, Any] | None = None) -> None:  # fmt: skip
        self.ctx.audit.record(audit_ctx(self.request, self.session), action, result=result, kind=kind, name=name,
                              namespace=namespace or "", detail=detail)  # fmt: skip


def audited(request: Request, ctx: AppContext = Depends(get_ctx)) -> Audited:
    return Audited(request, ctx)
