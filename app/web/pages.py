"""Page routes. Pages render skeletons and load data via the JSON API (fetch)."""

from __future__ import annotations

from flask import abort, render_template, request

from app.repositories import (
    ApplicationRepository,
    DeploymentRepository,
    EnvironmentRepository,
    HostGroupRepository,
    HostRepository,
    InstanceRepository,
    OperationRepository,
    RoleRepository,
    UserRepository,
    VersionRepository,
)
from app.security.rbac import require_permission
from app.services.application_service import ApplicationService
from app.services.dashboard_service import DashboardService
from app.services.deployment_service import DeploymentService
from app.services.settings_service import get_settings_service
from app.web import web


@web.get("/")
@require_permission("dashboard.view")
def dashboard():
    return render_template(
        "dashboard/index.html",
        summary=DashboardService().summary(),
        trend=DashboardService().deployment_trend(14),
    )


# --- infrastructure --------------------------------------------------------------------------------


@web.get("/hosts")
@require_permission("host.view")
def hosts_list():
    return render_template(
        "hosts/list.html",
        environments=EnvironmentRepository().all(),
        groups=HostGroupRepository().all(),
    )


@web.get("/hosts/new")
@require_permission("host.create")
def hosts_new():
    return render_template(
        "hosts/form.html",
        host=None,
        environments=EnvironmentRepository().all(),
        groups=HostGroupRepository().all(),
    )


@web.get("/hosts/<int:host_id>")
@require_permission("host.view")
def host_detail(host_id: int):
    host = HostRepository().get_or_404(host_id, "Host")
    return render_template(
        "hosts/detail.html",
        host=host,
        instances=InstanceRepository().for_host(host.id),
        deployments=DeploymentRepository().list(target_id=host.id, per_page=10).items,
    )


@web.get("/hosts/<int:host_id>/edit")
@require_permission("host.update")
def host_edit(host_id: int):
    host = HostRepository().get_or_404(host_id, "Host")
    return render_template(
        "hosts/form.html",
        host=host,
        environments=EnvironmentRepository().all(),
        groups=HostGroupRepository().all(),
    )


@web.get("/host-groups")
@require_permission("host.view")
def host_groups():
    return render_template(
        "hosts/groups.html",
        groups=HostGroupRepository().all(),
        hosts=HostRepository().all(),
        environments=EnvironmentRepository().all(),
    )


@web.get("/environments")
@require_permission("host.view")
def environments():
    return render_template(
        "hosts/environments.html",
        environments=EnvironmentRepository().all(),
        host_counts=HostRepository().counts_by_environment(),
    )


# --- applications ------------------------------------------------------------------------------------


@web.get("/applications")
@require_permission("application.view")
def applications_list():
    return render_template("applications/list.html")


@web.get("/applications/new")
@require_permission("application.create")
def applications_new():
    return render_template(
        "applications/form.html",
        application=None,
        environments=EnvironmentRepository().all(),
        groups=HostGroupRepository().all(),
    )


@web.get("/applications/<int:app_id>")
@require_permission("application.view")
def application_detail(app_id: int):
    app = ApplicationRepository().get_or_404(app_id, "Application")
    overview = ApplicationService().overview(app)
    return render_template(
        "applications/detail.html",
        application=app,
        overview=overview,
        environments=EnvironmentRepository().all(),
        hosts=HostRepository().enabled(),
    )


@web.get("/applications/<int:app_id>/edit")
@require_permission("application.update")
def application_edit(app_id: int):
    app = ApplicationRepository().get_or_404(app_id, "Application")
    return render_template(
        "applications/form.html",
        application=app,
        environments=EnvironmentRepository().all(),
        groups=HostGroupRepository().all(),
    )


@web.get("/applications/<int:app_id>/configuration")
@require_permission("configuration.view")
def application_configuration(app_id: int):
    app = ApplicationRepository().get_or_404(app_id, "Application")
    return render_template(
        "applications/configuration.html",
        application=app,
        environments=EnvironmentRepository().all(),
    )


@web.get("/releases")
@require_permission("package.view")
def releases_list():
    versions = []
    for app in ApplicationRepository().all():
        versions.extend(VersionRepository().for_application(app.id))
    versions.sort(key=lambda v: v.created_at, reverse=True)
    return render_template("applications/releases.html", versions=versions)


@web.get("/packages")
@require_permission("package.view")
def packages_list():
    return render_template("packages/list.html", applications=ApplicationRepository().all())


@web.get("/packages/upload")
@require_permission("package.upload")
def packages_upload():
    return render_template("packages/upload.html", applications=ApplicationRepository().all())


# --- operations --------------------------------------------------------------------------------------------


@web.get("/deployments")
@require_permission("deployment.view")
def deployments_list():
    return render_template(
        "deployments/list.html",
        applications=ApplicationRepository().all(),
        hosts=HostRepository().all(),
        environments=EnvironmentRepository().all(),
    )


@web.get("/deployments/new")
@require_permission("deployment.execute")
def deployments_wizard():
    app_id = request.args.get("application_id", type=int)
    host_id = request.args.get("host_id", type=int)
    return render_template(
        "deployments/wizard.html",
        applications=ApplicationRepository().all(),
        preselect_app=app_id,
        preselect_host=host_id,
        groups=HostGroupRepository().all(),
    )


@web.get("/deployments/<int:deployment_id>")
@require_permission("deployment.view")
def deployment_detail(deployment_id: int):
    service = DeploymentService()
    deployment = service.get(deployment_id)
    return render_template(
        "deployments/detail.html", deployment=deployment, timeline=service.timeline(deployment)
    )


@web.get("/operations")
@require_permission("deployment.view")
def operations_list():
    return render_template(
        "operations/list.html",
        applications=ApplicationRepository().all(),
        hosts=HostRepository().all(),
    )


@web.get("/operations/<int:operation_id>")
@require_permission("deployment.view")
def operation_detail(operation_id: int):
    operation = OperationRepository().get_or_404(operation_id, "Operation")
    return render_template("operations/detail.html", operation=operation)


@web.get("/jobs")
@require_permission("deployment.view")
def jobs():
    return render_template(
        "operations/jobs.html",
        active=OperationRepository().active(),
        running_deployments=[d for d in DeploymentRepository().recent(50) if not d.is_terminal],
    )


# --- monitoring ------------------------------------------------------------------------------------------------


@web.get("/monitoring/health")
@require_permission("health.view")
def monitoring_health():
    return render_template("monitoring/health.html", instances=InstanceRepository().all_active())


@web.get("/monitoring/logs")
@require_permission("logs.view")
def monitoring_logs():
    instances = [i for i in InstanceRepository().all_active() if i.current_version_id]
    app_id = request.args.get("application_id", type=int)
    host_id = request.args.get("host_id", type=int)
    return render_template(
        "monitoring/logs.html", instances=instances, preselect_app=app_id, preselect_host=host_id
    )


# --- security ------------------------------------------------------------------------------------------------------


@web.get("/security/users")
@require_permission("user.manage")
def users():
    return render_template(
        "security/users.html", users=UserRepository().all(), roles=RoleRepository().all()
    )


@web.get("/security/roles")
@require_permission("user.manage")
def roles():
    from app.security.rbac import PERMISSIONS

    grouped: dict[str, list[tuple[str, str]]] = {}
    for code, desc in PERMISSIONS.items():
        grouped.setdefault(code.split(".")[0], []).append((code, desc))
    return render_template("security/roles.html", roles=RoleRepository().all(), permissions=grouped)


@web.get("/security/credentials")
@require_permission("credential.manage")
def credentials():
    return render_template("security/credentials.html", hosts=HostRepository().all())


@web.get("/security/tokens")
@require_permission("dashboard.view")
def tokens():
    return render_template("security/tokens.html")


# --- audit / system -------------------------------------------------------------------------------------------------------


@web.get("/audit")
@require_permission("audit.view")
def audit_log():
    return render_template("audit/list.html", users=UserRepository().all())


@web.get("/audit/security-events")
@require_permission("audit.view")
def security_events():
    return render_template("audit/security_events.html")


@web.get("/system/settings")
@require_permission("system.manage")
def settings():
    return render_template("system/settings.html", settings=get_settings_service().all())


@web.get("/notifications")
@require_permission("notification.view")
def notifications():
    return render_template("system/notifications.html")


@web.get("/system/about")
@require_permission("dashboard.view")
def about():
    from app.runtimes.factory import RuntimeFactory

    return render_template("system/about.html", runtimes=RuntimeFactory.supported())


@web.get("/healthz")
def healthz():  # simple unauthenticated liveness for load balancers (mirrors /api/health)
    from app.api.health import health

    response, status = health()
    if status != 200:
        abort(503)
    return response
