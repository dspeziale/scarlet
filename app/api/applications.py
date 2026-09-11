"""Application, version, instance and lifecycle endpoints."""

from __future__ import annotations

from flask import request

from app.api import api
from app.api.responses import accepted, created, json_body, list_params, ok, paged, parse_bool
from app.errors import ValidationError
from app.repositories import (
    ApplicationRepository,
    DeploymentRepository,
    InstanceRepository,
    VersionRepository,
)
from app.security.rbac import get_current_user, require_permission
from app.services.application_service import ApplicationService
from app.services.configuration_service import ConfigurationService
from app.services.deployment_service import DeploymentService
from app.services.lifecycle_service import LifecycleService
from app.services.package_service import PackageService


def _app(app_id: int):
    return ApplicationRepository().get_or_404(app_id, "Application")


def _host_id(data: dict) -> int:
    host_id = data.get("host_id") or request.args.get("host_id")
    if not host_id:
        raise ValidationError("host_id is required.", errors={"host_id": ["Required."]})
    try:
        return int(host_id)
    except (TypeError, ValueError) as exc:
        raise ValidationError("host_id must be an integer.") from exc


@api.get("/applications")
@require_permission("application.view")
def list_applications():
    params = list_params(default_sort="name")
    page = ApplicationRepository().list(
        **params, runtime_type=(request.args.get("runtime") or "").upper() or None
    )
    return paged(page)


@api.post("/applications")
@require_permission("application.create")
def create_application():
    app = ApplicationService().create(json_body(), user=get_current_user())
    return created(app.to_dict())


@api.get("/applications/<int:app_id>")
@require_permission("application.view")
def get_application(app_id: int):
    return ok(ApplicationService().overview(_app(app_id)))


@api.put("/applications/<int:app_id>")
@api.patch("/applications/<int:app_id>")
@require_permission("application.update")
def update_application(app_id: int):
    app = ApplicationService().update(_app(app_id), json_body(), user=get_current_user())
    return ok(app.to_dict())


@api.delete("/applications/<int:app_id>")
@require_permission("application.delete")
def delete_application(app_id: int):
    ApplicationService().delete(_app(app_id), user=get_current_user())
    return ok({"deleted": True})


@api.get("/applications/<int:app_id>/versions")
@require_permission("application.view")
def list_versions(app_id: int):
    include_manifest = parse_bool(request.args.get("manifest"))
    return ok(
        [
            v.to_dict(include_manifest=include_manifest)
            for v in VersionRepository().for_application(_app(app_id).id)
        ]
    )


@api.get("/applications/<int:app_id>/versions/<int:version_id>")
@require_permission("application.view")
def get_version(app_id: int, version_id: int):
    version = VersionRepository().get_or_404(version_id, "Version")
    if version.application_id != app_id:
        raise ValidationError("Version does not belong to this application.")
    data = version.to_dict(include_manifest=True)
    data["integrity"] = PackageService().verify_integrity(version) if version.package else None
    return ok(data)


@api.post("/applications/<int:app_id>/versions/<int:version_id>/deactivate")
@require_permission("application.update")
def deactivate_version(app_id: int, version_id: int):
    version = VersionRepository().get_or_404(version_id, "Version")
    if version.application_id != app_id:
        raise ValidationError("Version does not belong to this application.")
    return ok(ApplicationService().deactivate_version(version, user=get_current_user()).to_dict())


@api.get("/applications/<int:app_id>/instances")
@require_permission("application.view")
def list_instances(app_id: int):
    return ok([i.to_dict() for i in InstanceRepository().for_application(_app(app_id).id)])


@api.get("/applications/<int:app_id>/compatible-hosts")
@require_permission("application.view")
def compatible_hosts(app_id: int):
    app = _app(app_id)
    version = None
    if request.args.get("version_id"):
        version = VersionRepository().get_or_404(int(request.args["version_id"]), "Version")
    return ok(ApplicationService().compatible_hosts(app, version))


@api.get("/applications/<int:app_id>/deployments")
@require_permission("deployment.view")
def application_deployments(app_id: int):
    params = list_params(default_sort="created_at")
    return paged(
        DeploymentRepository().list(
            **params, application_id=_app(app_id).id, target_id=request.args.get("host_id") or None
        )
    )


# --- lifecycle -------------------------------------------------------------------------------------


def _lifecycle(app_id: int, op: str, sync: bool = False):
    data = json_body(required=False)
    host_id = _host_id(data)
    operation = LifecycleService().request(
        op,
        application_id=_app(app_id).id,
        host_id=host_id,
        user=get_current_user(),
        reason=str(data.get("reason", "")),
        confirmation=data.get("confirmation"),
        parameters=data.get("parameters")
        or {k: v for k, v in request.args.items() if k in {"lines", "since", "search", "retries"}},
        sync=sync,
    )
    if operation.status_enum.is_terminal:
        return ok(operation.to_dict())
    return accepted(operation.to_dict(), poll=f"/api/operations/{operation.id}")


@api.post("/applications/<int:app_id>/start")
@require_permission("lifecycle.start")
def start_application(app_id: int):
    return _lifecycle(app_id, "START")


@api.post("/applications/<int:app_id>/stop")
@require_permission("lifecycle.stop")
def stop_application(app_id: int):
    return _lifecycle(app_id, "STOP")


@api.post("/applications/<int:app_id>/restart")
@require_permission("lifecycle.restart")
def restart_application(app_id: int):
    return _lifecycle(app_id, "RESTART")


@api.post("/applications/<int:app_id>/scale")
@require_permission("lifecycle.restart")
def scale_application(app_id: int):
    return _lifecycle(app_id, "SCALE")


@api.get("/applications/<int:app_id>/status")
@api.post("/applications/<int:app_id>/status")
@require_permission("lifecycle.status")
def status_application(app_id: int):
    return _lifecycle(app_id, "STATUS", sync=parse_bool(request.args.get("sync")))


@api.get("/applications/<int:app_id>/logs")
@api.post("/applications/<int:app_id>/logs")
@require_permission("logs.view")
def logs_application(app_id: int):
    return _lifecycle(app_id, "LOGS", sync=parse_bool(request.args.get("sync")))


@api.get("/applications/<int:app_id>/health")
@api.post("/applications/<int:app_id>/health")
@require_permission("health.execute")
def health_application(app_id: int):
    return _lifecycle(app_id, "HEALTH", sync=parse_bool(request.args.get("sync")))


@api.get("/applications/<int:app_id>/version")
@api.post("/applications/<int:app_id>/version")
@require_permission("application.view")
def version_application(app_id: int):
    return _lifecycle(app_id, "VERSION", sync=parse_bool(request.args.get("sync")))


@api.post("/applications/<int:app_id>/rollback")
@require_permission("deployment.rollback")
def rollback_application(app_id: int):
    data = json_body()
    deployment = DeploymentService().rollback(
        application_id=_app(app_id).id,
        host_id=_host_id(data),
        target_version_id=int(data["version_id"]) if data.get("version_id") else None,
        reason=str(data.get("reason", "")),
        confirmation=data.get("confirmation"),
        user=get_current_user(),
    )
    return accepted(deployment.to_dict(), poll=f"/api/deployments/{deployment.id}")


# --- configuration ----------------------------------------------------------------------------------


@api.get("/applications/<int:app_id>/configuration/<env_code>")
@require_permission("configuration.view")
def get_configuration(app_id: int, env_code: str):
    from app.repositories import EnvironmentRepository

    env = EnvironmentRepository().by_code(env_code)
    if env is None:
        raise ValidationError("Unknown environment.")
    config = ConfigurationService().get_or_create(_app(app_id), env)
    data = config.to_dict()
    data["versions"] = [v.to_dict() for v in config.versions]
    return ok(data)


@api.put("/applications/<int:app_id>/configuration/<env_code>")
@require_permission("configuration.update")
def update_configuration(app_id: int, env_code: str):
    from app.repositories import EnvironmentRepository
    from app.security.prod_guard import ProductionGuard
    from app.services.settings_service import get_settings_service

    env = EnvironmentRepository().by_code(env_code)
    if env is None:
        raise ValidationError("Unknown environment.")
    ProductionGuard(get_settings_service()).authorize("configuration.update", env)
    data = json_body()
    entries = data.get("entries")
    if not isinstance(entries, list):
        raise ValidationError("entries must be a list.")
    config = ConfigurationService().get_or_create(_app(app_id), env)
    version = ConfigurationService().set_entries(
        config, entries, user=get_current_user(), change_summary=str(data.get("change_summary", ""))
    )
    return ok({"configuration": config.to_dict(), "version": version.to_dict()})


@api.delete("/applications/<int:app_id>/configuration/<env_code>/<key>")
@require_permission("configuration.update")
def delete_configuration_key(app_id: int, env_code: str, key: str):
    from app.repositories import EnvironmentRepository
    from app.security.prod_guard import ProductionGuard
    from app.services.settings_service import get_settings_service

    env = EnvironmentRepository().by_code(env_code)
    if env is None:
        raise ValidationError("Unknown environment.")
    ProductionGuard(get_settings_service()).authorize("configuration.update", env)
    config = ConfigurationService().get_or_create(_app(app_id), env)
    version = ConfigurationService().delete_entry(config, key[:128], user=get_current_user())
    return ok({"configuration": config.to_dict(), "version": version.to_dict()})
