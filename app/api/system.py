"""System endpoints: settings, environments, host groups, notifications, dashboard."""

from __future__ import annotations

from flask import request

from app.api import api
from app.api.responses import created, json_body, list_params, ok, paged, parse_bool
from app.errors import ValidationError
from app.repositories import EnvironmentRepository, HostGroupRepository
from app.security.rbac import get_current_user, login_required_any, require_permission
from app.services.dashboard_service import DashboardService
from app.services.host_service import HostService
from app.services.notification_service import NotificationService
from app.services.settings_service import SETTING_DEFINITIONS, get_settings_service


@api.get("/dashboard")
@require_permission("dashboard.view")
def dashboard():
    return ok(DashboardService().summary())


@api.get("/dashboard/trend")
@require_permission("dashboard.view")
def dashboard_trend():
    try:
        days = min(max(int(request.args.get("days", 14)), 1), 90)
    except ValueError as exc:
        raise ValidationError("days must be an integer.") from exc
    return ok(DashboardService().deployment_trend(days))


# --- settings ---------------------------------------------------------------------------------


@api.get("/settings")
@require_permission("system.manage")
def list_settings():
    return ok(get_settings_service().all())


@api.put("/settings/<key>")
@require_permission("system.manage")
def update_setting(key: str):
    if key not in SETTING_DEFINITIONS:
        from app.errors import NotFoundError

        raise NotFoundError(f"Unknown setting {key}.")
    data = json_body()
    row = get_settings_service().set(key, data.get("value"), user=get_current_user())
    return ok(row.to_dict())


@api.delete("/settings/<key>")
@require_permission("system.manage")
def reset_setting(key: str):
    get_settings_service().reset(key[:64], user=get_current_user())
    return ok({"reset": True})


# --- environments ---------------------------------------------------------------------------------


@api.get("/environments")
@login_required_any
def list_environments():
    return ok([e.to_dict() for e in EnvironmentRepository().all()])


@api.put("/environments/<int:env_id>")
@require_permission("system.manage")
def update_environment(env_id: int):
    env = HostService().update_environment(
        EnvironmentRepository().get_or_404(env_id, "Environment"),
        json_body(),
        user=get_current_user(),
    )
    return ok(env.to_dict())


# --- host groups -----------------------------------------------------------------------------------


@api.get("/host-groups")
@require_permission("host.view")
def list_host_groups():
    params = list_params(default_sort="name")
    return paged(HostGroupRepository().list(**params))


@api.post("/host-groups")
@require_permission("host.create")
def create_host_group():
    data = json_body()
    group = HostService().create_group(
        name=str(data.get("name", "")),
        description=str(data.get("description", "")),
        environment_id=int(data["environment_id"]) if data.get("environment_id") else None,
        host_ids=[int(h) for h in data.get("host_ids") or []],
        user=get_current_user(),
    )
    return created(group.to_dict())


@api.get("/host-groups/<int:group_id>")
@require_permission("host.view")
def get_host_group(group_id: int):
    group = HostGroupRepository().get_or_404(group_id, "HostGroup")
    data = group.to_dict()
    data["hosts"] = [h.to_dict(include_system=False) for h in group.hosts]
    return ok(data)


@api.put("/host-groups/<int:group_id>")
@require_permission("host.update")
def update_host_group(group_id: int):
    data = json_body()
    group = HostService().update_group(
        HostGroupRepository().get_or_404(group_id, "HostGroup"),
        description=data.get("description"),
        environment_id=(
            int(data["environment_id"])
            if data.get("environment_id")
            else (0 if "environment_id" in data else None)
        ),
        host_ids=[int(h) for h in data["host_ids"]] if data.get("host_ids") is not None else None,
        user=get_current_user(),
    )
    return ok(group.to_dict())


@api.delete("/host-groups/<int:group_id>")
@require_permission("host.delete")
def delete_host_group(group_id: int):
    HostService().delete_group(
        HostGroupRepository().get_or_404(group_id, "HostGroup"), user=get_current_user()
    )
    return ok({"deleted": True})


# --- notifications --------------------------------------------------------------------------------------


@api.get("/notifications")
@require_permission("notification.view")
def list_notifications():
    user = get_current_user()
    service = NotificationService()
    return ok(
        {
            "items": [
                n.to_dict()
                for n in service.list_for(user, unread_only=parse_bool(request.args.get("unread")))
            ],
            "unread": service.unread_count(user),
        }
    )


@api.post("/notifications/read")
@require_permission("notification.view")
def mark_notifications_read():
    data = json_body(required=False)
    count = NotificationService().mark_read(
        get_current_user(), int(data["id"]) if data.get("id") else None
    )
    return ok({"marked": count})


# --- runtimes / metadata -------------------------------------------------------------------------------------


@api.get("/meta")
@login_required_any
def meta():
    from flask import current_app

    from app.models.enums import DeploymentStatus, HealthCheckType, OperationStatus, RuntimeType
    from app.runtimes.factory import RuntimeFactory

    return ok(
        {
            "version": current_app.config.get("APP_VERSION"),
            "environment": current_app.config.get("SCARLET_ENV"),
            "runtimes": RuntimeFactory.supported(),
            "runtime_types": RuntimeType.values(),
            "healthcheck_types": HealthCheckType.values(),
            "deployment_statuses": DeploymentStatus.values(),
            "operation_statuses": OperationStatus.values(),
            "max_upload_mb": current_app.config.get("SCARLET_MAX_UPLOAD_MB"),
        }
    )
