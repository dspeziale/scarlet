"""Error handling: typed exceptions -> JSON (API) or friendly HTML (web).

Tracebacks are never sent to clients; they are logged server-side together
with the request id, which is returned to the user for support purposes.
"""

from __future__ import annotations

from flask import Flask, g, jsonify, render_template, request
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from app.config.logging import get_logger
from app.errors import AuthenticationError, RateLimitError, ScarletError
from app.i18n import gettext as _

log = get_logger("scarlet.errors")


def _wants_json() -> bool:
    return request.path.startswith("/api/") or (
        request.accept_mimetypes.best == "application/json"
        and not request.accept_mimetypes.accept_html
    )


def _request_id() -> str | None:
    return getattr(g, "request_id", None)


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ScarletError)
    def handle_scarlet(exc: ScarletError):
        status = exc.http_status
        if status >= 500:
            log.error(
                "scarlet error %s: %s",
                exc.code,
                exc.message,
                exc_info=True,
                extra={"extra_data": {"details": exc.details}},
            )
        else:
            log.info(
                "scarlet error %s: %s",
                exc.code,
                exc.message,
                extra={"extra_data": {"details": exc.details}},
            )
        if _wants_json():
            body = exc.to_dict()
            body["request_id"] = _request_id()
            if exc.details and status < 500:
                safe = {
                    k: v
                    for k, v in exc.details.items()
                    if k
                    in {
                        "expected",
                        "permission",
                        "production",
                        "fingerprint",
                        "key_type",
                        "lock_key",
                        "from",
                        "to",
                        "runtime_type",
                        "presented_fingerprint",
                        "problems",
                        "missing",
                    }
                }
                if safe:
                    body["details"] = safe
            return jsonify({"ok": False, "error": body}), status
        if isinstance(exc, AuthenticationError):
            from flask import redirect, url_for

            return redirect(url_for("web_auth.login", next=request.full_path))
        return (
            render_template(
                "errors/error.html",
                status=status,
                title=_title_for(status),
                message=_(exc.message),
                code=exc.code,
                request_id=_request_id(),
            ),
            status,
        )

    @app.errorhandler(CSRFError)
    def handle_csrf(exc: CSRFError):
        if _wants_json():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "code": "CSRF_ERROR",
                            "message": "Invalid or missing CSRF token.",
                            "request_id": _request_id(),
                        },
                    }
                ),
                400,
            )
        return (
            render_template(
                "errors/error.html",
                status=400,
                title="Request rejected",
                message="The security token of the form is invalid or expired. Please reload the page and try again.",
                code="CSRF_ERROR",
                request_id=_request_id(),
            ),
            400,
        )

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(exc):
        limit = app.config.get("SCARLET_MAX_UPLOAD_MB")
        message = f"The uploaded file exceeds the maximum allowed size ({limit} MB)."
        if _wants_json():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": message,
                            "request_id": _request_id(),
                        },
                    }
                ),
                413,
            )
        return (
            render_template(
                "errors/error.html",
                status=413,
                title="Upload too large",
                message=message,
                code="PAYLOAD_TOO_LARGE",
                request_id=_request_id(),
            ),
            413,
        )

    @app.errorhandler(429)
    def handle_rate_limit(exc):
        err = RateLimitError()
        if _wants_json():
            return (
                jsonify({"ok": False, "error": {**err.to_dict(), "request_id": _request_id()}}),
                429,
            )
        return (
            render_template(
                "errors/error.html",
                status=429,
                title="Too many requests",
                message=err.message,
                code=err.code,
                request_id=_request_id(),
            ),
            429,
        )

    @app.errorhandler(HTTPException)
    def handle_http(exc: HTTPException):
        status = exc.code or 500
        if _wants_json():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "code": (exc.name or "HTTP_ERROR").upper().replace(" ", "_"),
                            "message": exc.description if status < 500 else "Server error.",
                            "request_id": _request_id(),
                        },
                    }
                ),
                status,
            )
        return (
            render_template(
                "errors/error.html",
                status=status,
                title=_title_for(status),
                message=_(exc.description) if status < 500 else _("An internal error occurred."),
                code=(exc.name or "").upper().replace(" ", "_"),
                request_id=_request_id(),
            ),
            status,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        log.exception("unhandled exception")
        from app.extensions import db

        try:
            db.session.rollback()
        except Exception:  # noqa: BLE001
            pass
        message = (
            "An internal error occurred. Please contact an administrator and quote the request id."
        )
        if app.debug and not app.config.get("SCARLET_ENV") == "production":
            message = f"{type(exc).__name__}: {exc}"
        if _wants_json():
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": message,
                            "request_id": _request_id(),
                        },
                    }
                ),
                500,
            )
        return (
            render_template(
                "errors/error.html",
                status=500,
                title="Internal error",
                message=message,
                code="INTERNAL_ERROR",
                request_id=_request_id(),
            ),
            500,
        )


def _title_for(status: int) -> str:
    return _(
        {
            400: "Bad request",
            401: "Authentication required",
            403: "Access denied",
            404: "Not found",
            409: "Conflict",
            413: "Too large",
            429: "Too many requests",
            500: "Internal error",
            502: "Remote error",
            504: "Timeout",
        }.get(status, "Error")
    )
