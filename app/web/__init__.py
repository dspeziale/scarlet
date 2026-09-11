"""Server-rendered AdminLTE UI. Pages fetch live data through the JSON API."""

from __future__ import annotations

from flask import Blueprint, Flask, current_app, request

from app.extensions import csrf

web = Blueprint("web", __name__)
web_auth = Blueprint("web_auth", __name__)


@web.before_request
@web_auth.before_request
def _web_csrf() -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and current_app.config.get(
        "WTF_CSRF_ENABLED", True
    ):
        csrf.protect()


def register_web(app: Flask) -> None:
    from app.web import auth, pages  # noqa: F401 - route modules register on the blueprints

    app.register_blueprint(web_auth)
    app.register_blueprint(web)
