"""Application factory."""

from __future__ import annotations

import structlog

from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_talisman import Talisman

from config import get_config
from app.extensions import db
from app.logging_config import configure_logging

log = structlog.get_logger(__name__)

jwt = JWTManager()
limiter = Limiter(key_func=get_remote_address)
migrate = Migrate()
talisman = Talisman()


def create_app(env: str | None = None) -> Flask:
    cfg = get_config(env)
    configure_logging(cfg)

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config.from_object(cfg)

    # ── Reverse-proxy trust (Vercel / any load-balancer that terminates TLS) ──
    # Must come BEFORE Talisman so request.is_secure reflects the original scheme.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)  # type: ignore[assignment]

    # ── Extensions ─────────────────────────────────────────────────────────
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    limiter.init_app(app)
    CORS(app, origins=cfg.CORS_ORIGINS, supports_credentials=True)

    if not app.testing:
        talisman.init_app(
            app,
            force_https=cfg.TALISMAN_FORCE_HTTPS,
            content_security_policy=cfg.TALISMAN_CONTENT_SECURITY_POLICY,
            strict_transport_security=True,
            referrer_policy="strict-origin-when-cross-origin",
            frame_options="DENY",
        )

    # ── JWT callbacks ──────────────────────────────────────────────────────
    _register_jwt_callbacks(jwt)

    # ── Blueprints ─────────────────────────────────────────────────────────
    _register_blueprints(app)

    # ── Error handlers ─────────────────────────────────────────────────────
    _register_error_handlers(app)

    # ── Correlation-ID middleware (outermost — after ProxyFix) ─────────────
    from app.middleware.correlation import CorrelationIdMiddleware
    app.wsgi_app = CorrelationIdMiddleware(app.wsgi_app)  # type: ignore[assignment]

    # ── Lightweight schema self-heal ───────────────────────────────────────
    # The deployment provisions schema via db.create_all() (seed.py), which
    # creates missing tables but never adds new columns to existing ones.
    # Add idempotently the columns introduced after first deploy so the app
    # doesn't 500 on a DB that predates them. Best-effort: never fatal.
    if not app.testing:
        _ensure_schema(app)

    log.info("app_started", env=env or "default")
    return app


# Columns added after the initial schema, keyed by table. Dialect-portable types.
_SCHEMA_ADDITIONS: dict[str, dict[str, str]] = {
    "probes": {
        "interfaces": "JSON",
        "subnets": "JSON",
        "ids_interface": "VARCHAR(64)",
        "network_updated_at": "TIMESTAMP",
        "ruleset_version": "VARCHAR(40)",
        "location": "VARCHAR(255)",
        "latitude": "DOUBLE PRECISION",
        "longitude": "DOUBLE PRECISION",
        "contact_name": "VARCHAR(120)",
        "contact_email": "VARCHAR(255)",
        "telegram_id": "VARCHAR(64)",
        "notes": "TEXT",
    },
    "device_inventory": {
        "details": "JSON",
    },
    "tenants": {
        "notify_enabled": "BOOLEAN",
        "telegram_bot_token": "VARCHAR(120)",
        "telegram_chat_id": "VARCHAR(64)",
        "gmail_address": "VARCHAR(255)",
        "gmail_app_password": "VARCHAR(255)",
        "notify_email": "VARCHAR(255)",
    },
}


def _ensure_schema(app: Flask) -> None:
    """Add missing columns to existing tables (idempotent, best-effort)."""
    from sqlalchemy import inspect, text
    from app.extensions import db

    try:
        with app.app_context():
            import app.models  # noqa: F401 — ensure every model is registered
            # Create any tables introduced by new models (idempotent — never
            # touches existing tables). Covers new features on a DB that predates
            # them, since the deployment has no migration step.
            try:
                db.create_all()
            except Exception as exc:  # pragma: no cover
                log.warning("schema_create_all_failed", error=str(exc))

            inspector = inspect(db.engine)
            tables = set(inspector.get_table_names())
            for table, columns in _SCHEMA_ADDITIONS.items():
                if table not in tables:
                    continue  # fresh DB — create_all/seed will build it fully
                existing = {c["name"] for c in inspector.get_columns(table)}
                missing = {n: t for n, t in columns.items() if n not in existing}
                if not missing:
                    continue
                with db.engine.begin() as conn:
                    for name, sql_type in missing.items():
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
                log.info("schema_self_heal", table=table, added=list(missing))
    except Exception as exc:  # pragma: no cover — never block startup
        log.warning("schema_self_heal_failed", error=str(exc))


def _register_blueprints(app: Flask) -> None:
    from app.api.v1 import api_v1_bp
    from app.web.views import web_bp

    app.register_blueprint(api_v1_bp, url_prefix="/api/v1")
    app.register_blueprint(web_bp)


def _register_error_handlers(app: Flask) -> None:
    from flask import jsonify

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify(error="bad_request", message=str(e)), 400

    @app.errorhandler(401)
    def unauthorized(e):
        return jsonify(error="unauthorized", message=str(e)), 401

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify(error="forbidden", message=str(e)), 403

    @app.errorhandler(404)
    def not_found(e):
        return jsonify(error="not_found", message=str(e)), 404

    @app.errorhandler(422)
    def unprocessable(e):
        return jsonify(error="unprocessable_entity", message=str(e)), 422

    @app.errorhandler(429)
    def ratelimit(e):
        return jsonify(error="rate_limit_exceeded", message=str(e)), 429

    @app.errorhandler(500)
    def internal_error(e):
        log.error("internal_server_error", error=str(e))
        return jsonify(error="internal_server_error", message="An unexpected error occurred"), 500


def _register_jwt_callbacks(jwt_manager: JWTManager) -> None:
    from flask import jsonify
    from app.models.token_blocklist import TokenBlocklist
    from app.extensions import db

    @jwt_manager.token_in_blocklist_loader
    def check_if_token_revoked(_jwt_header, jwt_payload):
        jti = jwt_payload["jti"]
        token = db.session.query(TokenBlocklist).filter_by(jti=jti).scalar()
        return token is not None

    @jwt_manager.revoked_token_loader
    def revoked_token_callback(_jwt_header, _jwt_payload):
        return jsonify(error="token_revoked", message="Token has been revoked"), 401

    @jwt_manager.expired_token_loader
    def expired_token_callback(_jwt_header, _jwt_payload):
        return jsonify(error="token_expired", message="Token has expired"), 401

    @jwt_manager.invalid_token_loader
    def invalid_token_callback(reason):
        return jsonify(error="invalid_token", message=reason), 401

    @jwt_manager.unauthorized_loader
    def missing_token_callback(reason):
        return jsonify(error="authorization_required", message=reason), 401
