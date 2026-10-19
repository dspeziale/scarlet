"""ASGI application factory."""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import API_VERSION, __version__
from .config import Settings
from .context import AppContext
from .errors import AppError
from .logging_setup import request_id_var
from .security.users import SETUP_TOKEN_KEY, new_setup_token

log = logging.getLogger("pkm.http")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
       "object-src 'none'")  # fmt: skip


def _error_body(code: str, message: str, request_id: str | None, *, params: dict[str, Any] | None = None,
                details: str | None = None) -> dict[str, Any]:  # fmt: skip
    return {"error": {"code": code, "message": message, "params": params or {}, "details": details,
                      "requestId": request_id}}  # fmt: skip


def create_app(settings: Settings, *, start_background: bool = True) -> FastAPI:
    ctx_holder: dict[str, AppContext] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        ctx = ctx_holder["ctx"]
        if ctx.users.count() == 0 and not ctx.db.get_state(SETUP_TOKEN_KEY):
            token = new_setup_token(ctx.db)
            # Readable only by whoever can read the service log (root / adm group on the server).
            log.warning("first run: open the web interface and use this one-time setup token",
                        extra={"setup_token": token})
        if start_background:
            ctx.start_monitor()
        log.info("PKM started", extra={"version": __version__, "mode": settings.mode, "env": settings.environment})
        yield
        await ctx.stop()
        log.info("PKM stopped")

    dev = settings.environment == "development"
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        description="REST API of Podman Kubernetes Manager. All endpoints except /system/info, /setup/* and "
                    "/auth/login require a session cookie; state-changing requests also need the X-CSRF-Token header.",
        openapi_url=f"/api/{API_VERSION}/openapi.json",
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    ctx = AppContext(settings)
    ctx_holder["ctx"] = ctx
    app.state.ctx = ctx

    # ------------------------------------------------------------ middleware
    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = request.headers.get("x-request-id", "")
        if not REQUEST_ID_RE.match(rid):
            rid = uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.monotonic()
        path = request.url.path
        try:
            if path.startswith("/api/") and path not in ("/api/v1/auth/login",):
                from .api.deps import client_ip

                key = request.cookies.get("__Host-pkm_session") or request.cookies.get("pkm_session") or \
                    f"ip:{client_ip(request, ctx)}"  # fmt: skip
                if not ctx.api_limiter.hit(key[:80]):
                    response: Response = JSONResponse(
                        _error_body("rate_limited", "too many requests", rid,
                                    params={"retryAfter": ctx.api_limiter.retry_after(key[:80])}), status_code=429)  # fmt: skip
                else:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"path": path})
            response = JSONResponse(_error_body("internal_error", "unexpected server error", rid), status_code=500)
        finally:
            request_id_var.reset(token)
        elapsed = int((time.monotonic() - start) * 1000)
        response.headers["X-Request-ID"] = rid
        response.headers["X-PKM-Mode"] = ctx.settings.mode
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if not path.startswith("/api/docs"):
            response.headers["Content-Security-Policy"] = CSP
        if settings.server.tls_enabled:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            if path not in ("/api/v1/stream",) and not path.endswith("/logs/stream"):
                log.info("request", extra={"method": request.method, "path": path, "status": response.status_code,
                                           "ms": elapsed, "request_id": rid})  # fmt: skip
        return response

    # ------------------------------------------------------------ errors
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        rid = request_id_var.get()
        if exc.status_code >= 500:
            log.warning("request failed", extra={"code": exc.code, "error": exc.message, "path": request.url.path})
        return JSONResponse(_error_body(exc.code, exc.message, rid, params=exc.params, details=exc.details),
                            status_code=exc.status_code)  # fmt: skip

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")),
                   "message": e["msg"], "type": e["type"]} for e in exc.errors()]  # fmt: skip
        return JSONResponse(_error_body("validation_failed", "invalid input", request_id_var.get(),
                                        params={"errors": errors}), status_code=422)  # fmt: skip

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(_error_body(code, str(exc.detail), request_id_var.get()), status_code=exc.status_code)

    # ------------------------------------------------------------ routes
    from .api import (
        routes_admin,
        routes_auth,
        routes_cluster,
        routes_k8s,
        routes_monitoring,
        routes_podman,
        routes_setup,
    )

    prefix = f"/api/{API_VERSION}"
    for r in (routes_auth, routes_setup, routes_cluster, routes_k8s, routes_podman, routes_monitoring, routes_admin):
        app.include_router(r.router, prefix=prefix)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        try:
            ctx.db.ping()
        except Exception:
            return JSONResponse({"status": "unavailable", "database": "error"}, status_code=503)
        return JSONResponse({"status": "ok", "version": __version__, "mode": settings.mode})

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str) -> JSONResponse:
        return JSONResponse(_error_body("not_found", f"unknown API endpoint /api/{rest}", request_id_var.get()),
                            status_code=404)  # fmt: skip

    static_dir = Path(settings.server.static_dir) if settings.server.static_dir else Path(__file__).parent / "static"
    index = static_dir / "index.html"
    if index.is_file():
        root = static_dir.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
                return FileResponse(candidate, headers=headers)
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
    else:
        @app.get("/", include_in_schema=False)
        def no_ui() -> JSONResponse:
            return JSONResponse({"message": "PKM API is running; the web UI is not built (frontend/dist missing).",
                                 "api": f"{prefix}/openapi.json"})  # fmt: skip

    return app
