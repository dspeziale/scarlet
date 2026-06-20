"""Server-rendered AdminLTE dashboard views (protected via session cookie or JWT)."""

from flask import Blueprint, redirect, render_template, url_for

web_bp = Blueprint("web", __name__)


@web_bp.get("/")
def index():
    return redirect(url_for("web.dashboard"))


@web_bp.get("/favicon.ico")
def favicon():
    """No favicon asset — return 204 to silence the browser's 404 request."""
    return ("", 204)


@web_bp.get("/login")
def login_page():
    return render_template("auth/login.html")


@web_bp.get("/dashboard")
def dashboard():
    return render_template("tenant/dashboard.html")


@web_bp.get("/superadmin/tenants")
def superadmin_tenants():
    return render_template("superadmin/tenants.html")


@web_bp.get("/superadmin/users")
def superadmin_users():
    return render_template("superadmin/users.html")


@web_bp.get("/superadmin/audit")
def superadmin_audit():
    return render_template("superadmin/audit.html")


@web_bp.get("/superadmin/stats")
def superadmin_stats():
    return render_template("superadmin/stats.html")


@web_bp.get("/tenant/probes")
def tenant_probes():
    return render_template("tenant/probes.html")


@web_bp.get("/tenant/tasks")
def tenant_tasks():
    return render_template("tenant/tasks.html")


@web_bp.get("/tenant/results")
def tenant_results():
    return render_template("tenant/results.html")


@web_bp.get("/tenant/accounting")
def tenant_accounting():
    return render_template("tenant/accounting.html")


@web_bp.get("/tenant/users")
def tenant_users():
    return render_template("tenant/users.html")


@web_bp.get("/tenant/audit")
def tenant_audit():
    return render_template("tenant/audit.html")


@web_bp.get("/tenant/settings")
def tenant_settings():
    return render_template("tenant/settings.html")


@web_bp.get("/tenant/ids")
def tenant_ids():
    return render_template("tenant/ids.html")


