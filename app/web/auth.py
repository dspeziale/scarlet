"""Login / logout / password pages."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import current_app, flash, redirect, render_template, request, url_for

from app.errors import AuthenticationError, ScarletError
from app.extensions import limiter
from app.security.rbac import get_current_user, login_required_any
from app.services.auth_service import AuthService
from app.web import web_auth


def _safe_next(target: str | None) -> str:
    if not target:
        return url_for("web.dashboard")
    parsed = urlparse(target)
    if parsed.netloc or parsed.scheme or not target.startswith("/") or target.startswith("//"):
        return url_for("web.dashboard")
    return target


@web_auth.route("/login", methods=["GET", "POST"])
@limiter.limit(
    lambda: current_app.config.get("SCARLET_LOGIN_RATE_LIMIT", "5 per minute"),
    methods=["POST"],
    deduct_when=lambda resp: resp.status_code != 302,
)
def login():
    if get_current_user() is not None:
        return redirect(url_for("web.dashboard"))
    error = None
    if request.method == "POST":
        try:
            user = AuthService().authenticate(
                request.form.get("username", "")[:64],
                request.form.get("password", "")[:256],
                remember=bool(request.form.get("remember")),
            )
            if user.must_change_password:
                flash("You must change your password before continuing.", "warning")
                return redirect(url_for("web_auth.change_password"))
            return redirect(_safe_next(request.args.get("next") or request.form.get("next")))
        except AuthenticationError as exc:
            error = exc.message
        except ScarletError as exc:
            error = exc.message
    return render_template("auth/login.html", error=error, next=request.args.get("next", "")), (
        401 if error else 200
    )


@web_auth.post("/logout")
@login_required_any
def logout():
    AuthService().logout(get_current_user())
    flash("You have been signed out.", "info")
    return redirect(url_for("web_auth.login"))


@web_auth.route("/password", methods=["GET", "POST"])
@login_required_any
def change_password():
    user = get_current_user()
    error = None
    if request.method == "POST":
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        if new != confirm:
            error = "The new passwords do not match."
        else:
            try:
                AuthService().change_password(user, request.form.get("current_password", ""), new)
                flash("Password changed. Please sign in again.", "success")
                AuthService().logout(user)
                return redirect(url_for("web_auth.login"))
            except ScarletError as exc:
                error = exc.message
                if getattr(exc, "errors", None):
                    error = " ".join(" ".join(v) for v in exc.errors.values())
    return render_template("auth/password.html", error=error, forced=user.must_change_password)
