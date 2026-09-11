"""SCARLET application factory."""

from __future__ import annotations

import os
from typing import Any

from flask import Flask, g, request
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import build_config
from app.config.logging import bind_context, configure_logging, reset_context
from app.utils.ids import new_request_id

__version__ = "1.0.0"


def create_app(overrides: dict[str, Any] | None = None) -> Flask:
    from dotenv import load_dotenv

    load_dotenv(override=False)
    cfg = build_config(overrides)
    configure_logging(cfg.SCARLET_LOG_LEVEL, cfg.SCARLET_LOG_FORMAT)

    app = Flask(
        __name__, template_folder="templates", static_folder="static", static_url_path="/static"
    )
    app.config.from_object(cfg)
    app.config["SCARLET_CONFIG"] = cfg
    app.json.sort_keys = False

    if cfg.SCARLET_TRUSTED_PROXIES:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=cfg.SCARLET_TRUSTED_PROXIES,
            x_proto=cfg.SCARLET_TRUSTED_PROXIES,
            x_host=cfg.SCARLET_TRUSTED_PROXIES,
        )

    for path in (cfg.SCARLET_ARTIFACT_PATH, cfg.SCARLET_UPLOAD_TMP_PATH, cfg.SCARLET_LOG_PATH):
        os.makedirs(path, exist_ok=True)

    _init_extensions(app)
    _register_request_hooks(app)
    _register_blueprints(app)
    _register_template_helpers(app)

    from app.api.errors import register_error_handlers
    from app.cli import register_cli
    from app.security.headers import register_security_headers
    from app.tasks.celery_app import init_celery

    register_error_handlers(app)
    register_security_headers(app)
    register_cli(app)
    init_celery(app)
    return app


def _init_extensions(app: Flask) -> None:
    from app import models  # noqa: F401 - register mappers
    from app.extensions import csrf, db, limiter, migrate
    from app.security.auth import register_auth

    db.init_app(app)
    migrate.init_app(
        app, db, directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
    )
    csrf.init_app(app)
    limiter.init_app(app)
    register_auth(app)


def _register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _bind_request_context() -> None:
        incoming = request.headers.get("X-Request-ID", "")
        request_id = (
            incoming
            if incoming and len(incoming) <= 64 and incoming.replace("-", "").isalnum()
            else new_request_id()
        )
        g.request_id = request_id
        g.pop(
            "_login_user", None
        )  # never reuse a cached login across requests sharing an app context
        g._log_token = bind_context(request_id=request_id)

    @app.after_request
    def _stamp_request_id(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        return response

    @app.teardown_request
    def _reset(exc) -> None:
        token = getattr(g, "_log_token", None)
        reset_context(token)


def _register_blueprints(app: Flask) -> None:
    from app.api import register_api
    from app.web import register_web

    register_api(app)
    register_web(app)


def _register_template_helpers(app: Flask) -> None:
    from app.web.helpers import register_template_helpers

    register_template_helpers(app)
