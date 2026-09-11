"""Jinja helpers: badges, formatting, permission checks, asset URLs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from flask import Flask, current_app, g, request
from flask_wtf.csrf import generate_csrf
from markupsafe import Markup, escape

from app.security.rbac import get_current_user, user_has_permission

CDN = {
    "adminlte_css": "https://cdn.jsdelivr.net/npm/admin-lte@4.3.1/dist/css/adminlte.min.css",
    "adminlte_js": "https://cdn.jsdelivr.net/npm/admin-lte@4.3.1/dist/js/adminlte.min.js",
    "bootstrap_js": "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
    "bootstrap_icons_css": "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css",
    "fontawesome_css": "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.6.0/css/all.min.css",
    "chartjs": "https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js",
    "swagger_css": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css",
    "swagger_js": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js",
}
LOCAL = {
    "adminlte_css": "vendor/adminlte/adminlte.min.css",
    "adminlte_js": "vendor/adminlte/adminlte.min.js",
    "bootstrap_js": "vendor/bootstrap/bootstrap.bundle.min.js",
    "bootstrap_icons_css": "vendor/bootstrap-icons/bootstrap-icons.min.css",
    "fontawesome_css": "vendor/fontawesome/all.min.css",
    "chartjs": "vendor/chartjs/chart.umd.min.js",
    "swagger_css": "vendor/swagger/swagger-ui.css",
    "swagger_js": "vendor/swagger/swagger-ui-bundle.js",
}

STATUS_CLASSES: dict[str, str] = {
    # hosts
    "ONLINE": "success",
    "OFFLINE": "danger",
    "UNKNOWN": "secondary",
    "DISABLED": "dark",
    # application state
    "RUNNING": "success",
    "STOPPED": "secondary",
    "STARTING": "info",
    "STOPPING": "info",
    "FAILED": "danger",
    "NOT_INSTALLED": "light text-dark",
    # health
    "HEALTHY": "success",
    "UNHEALTHY": "danger",
    # deployment / operation
    "SUCCESS": "success",
    "QUEUED": "secondary",
    "CREATED": "secondary",
    "PENDING_APPROVAL": "warning text-dark",
    "APPROVED": "info",
    "CANCELLED": "dark",
    "REJECTED": "dark",
    "TIMEOUT": "danger",
    "ROLLED_BACK": "warning text-dark",
    "ROLLBACK_REQUIRED": "warning text-dark",
    "ROLLING_BACK": "warning text-dark",
    # steps
    "PENDING": "light text-dark",
    "SKIPPED": "secondary",
    # packages
    "VALID": "success",
    "INVALID": "danger",
    "VALIDATING": "info",
    "UPLOADED": "secondary",
    "QUARANTINED": "danger",
    # host keys
    "MISMATCH": "danger",
    "REVOKED": "dark",
    # audit
    "DENIED": "warning text-dark",
    "INFO": "info",
    "FAILURE": "danger",
    # environments
    "DEV": "success",
    "PROD": "danger",
    # severity
    "LOW": "secondary",
    "MEDIUM": "info",
    "HIGH": "warning text-dark",
    "CRITICAL": "danger",
}


def status_badge(value: Any, *, extra_class: str = "") -> Markup:
    if value is None:
        value = "UNKNOWN"
    text = str(value)
    cls = STATUS_CLASSES.get(
        text.upper(),
        (
            "info"
            if text.upper().endswith("ING")
            else ("danger" if "FAIL" in text.upper() else "secondary")
        ),
    )
    return Markup(
        f'<span class="badge text-bg-{escape(cls)} {escape(extra_class)}" data-status="{escape(text)}">{escape(text.replace("_", " "))}</span>'
    )


def env_badge(code: Any, is_production: bool | None = None) -> Markup:
    text = str(code or "?")
    prod = is_production if is_production is not None else text.upper() == "PROD"
    cls = "danger" if prod else "success"
    icon = "fa-triangle-exclamation" if prod else "fa-flask"
    return Markup(
        f'<span class="badge text-bg-{cls} env-badge"><i class="fa-solid {icon} me-1"></i>{escape(text)}</span>'
    )


def runtime_icon(runtime: Any) -> Markup:
    icons = {
        "DOCKER": "fa-brands fa-docker",
        "PODMAN": "fa-solid fa-cube",
        "KUBERNETES": "fa-solid fa-dharmachakra",
        "NONE": "fa-solid fa-ban",
    }
    rt = str(runtime or "NONE").upper()
    return Markup(
        f'<i class="{icons.get(rt, "fa-solid fa-question")} me-1" title="{escape(rt)}"></i>{escape(rt)}'
    )


def fmt_dt(value: Any, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if not value:
        return "-"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return value.strftime(fmt) + " UTC"


def fmt_bytes(value: Any) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def fmt_duration(value: Any) -> str:
    if value is None:
        return "-"
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def register_template_helpers(app: Flask) -> None:
    app.jinja_env.filters["status_badge"] = status_badge
    app.jinja_env.filters["env_badge"] = env_badge
    app.jinja_env.filters["runtime_icon"] = runtime_icon
    app.jinja_env.filters["dt"] = fmt_dt
    app.jinja_env.filters["filesize"] = fmt_bytes
    app.jinja_env.filters["duration"] = fmt_duration

    @app.context_processor
    def _inject() -> dict[str, Any]:
        user = get_current_user()
        mode = current_app.config.get("SCARLET_ASSET_MODE", "cdn")

        def asset(name: str) -> str:
            if mode == "local":
                from flask import url_for

                return url_for("static", filename=LOCAL[name])
            return CDN[name]

        def can(permission: str, production: bool = False) -> bool:
            return user_has_permission(user, permission, production=production)

        unread = 0
        if user is not None:
            try:
                from app.services.notification_service import NotificationService

                unread = NotificationService().unread_count(user)
            except Exception:  # noqa: BLE001
                unread = 0
        return {
            "current_user_obj": user,
            "can": can,
            "asset": asset,
            "csrf_token_value": generate_csrf(),
            "scarlet_env": current_app.config.get("SCARLET_ENV"),
            "scarlet_version": current_app.config.get("APP_VERSION"),
            "request_id": getattr(g, "request_id", None),
            "unread_notifications": unread,
            "active_path": request.path,
            "prod_phrase": current_app.config.get(
                "SCARLET_PROD_CONFIRMATION_PHRASE", "DEPLOY TO PROD"
            ),
            "api_docs_enabled": current_app.config.get("SCARLET_API_DOCS_ENABLED", True),
        }
