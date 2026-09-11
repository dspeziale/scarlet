"""Host endpoints."""

from __future__ import annotations

from app.api import api
from app.api.responses import accepted, created, json_body, list_params, ok, paged, parse_bool
from app.config.logging import current_context
from app.models.enums import OperationType
from app.repositories import HostRepository, InstanceRepository
from app.security.prod_guard import ProductionGuard
from app.security.rbac import get_current_user, require_permission
from app.services.host_key_service import HostKeyService
from app.services.host_service import HostService
from app.services.operation_service import OperationService
from app.services.settings_service import get_settings_service


def _host(host_id: int):
    return HostRepository().get_or_404(host_id, "Host")


@api.get("/hosts")
@require_permission("host.view")
def list_hosts():
    params = list_params(default_sort="name")
    from flask import request

    page = HostRepository().list(
        **params,
        environment=request.args.get("environment"),
        runtime_type=(request.args.get("runtime") or "").upper() or None,
        status=request.args.get("status"),
        group_id=request.args.get("group_id"),
    )
    return paged(page, lambda h: h.to_dict(include_system=False))


@api.post("/hosts")
@require_permission("host.create")
def create_host():
    host = HostService().create(json_body(), user=get_current_user())
    return created(host.to_dict())


@api.get("/hosts/<int:host_id>")
@require_permission("host.view")
def get_host(host_id: int):
    host = _host(host_id)
    data = host.to_dict()
    data["capabilities"] = [c.to_dict() for c in host.capabilities]
    data["credentials"] = [c.to_dict() for c in host.credentials]
    data["instances"] = [i.to_dict() for i in InstanceRepository().for_host(host.id)]
    data["discovery"] = host.discovery_data
    return ok(data)


@api.put("/hosts/<int:host_id>")
@api.patch("/hosts/<int:host_id>")
@require_permission("host.update")
def update_host(host_id: int):
    host = _host(host_id)
    ProductionGuard(get_settings_service()).authorize("host.update", host.environment)
    host = HostService().update(host, json_body(), user=get_current_user())
    return ok(host.to_dict())


@api.delete("/hosts/<int:host_id>")
@require_permission("host.delete")
def delete_host(host_id: int):
    host = _host(host_id)
    guard = ProductionGuard(get_settings_service())
    guard.authorize("host.delete", host.environment)
    data = json_body(required=False)
    guard.check_operation(
        environment=host.environment,
        operation="DELETE",
        confirmation=data.get("confirmation"),
        reason=data.get("reason"),
    )
    HostService().delete(host, user=get_current_user())
    return ok({"deleted": True})


@api.post("/hosts/<int:host_id>/enable")
@api.post("/hosts/<int:host_id>/disable")
@require_permission("host.update")
def toggle_host(host_id: int):
    from flask import request

    host = _host(host_id)
    ProductionGuard(get_settings_service()).authorize("host.update", host.environment)
    enabled = request.path.endswith("/enable")
    HostService().set_enabled(host, enabled, user=get_current_user())
    return ok(host.to_dict(include_system=False))


@api.post("/hosts/<int:host_id>/credentials")
@require_permission("credential.manage")
def set_credential(host_id: int):
    host = _host(host_id)
    data = json_body()
    cred = HostService().set_credential(
        host,
        credential_type=str(data.get("credential_type", "")),
        secret=str(data.get("secret", "")),
        passphrase=(data.get("passphrase") or None),
        username=(data.get("username") or None),
        user=get_current_user(),
    )
    return created(cred.to_dict())


@api.delete("/hosts/<int:host_id>/credentials/<int:credential_id>")
@require_permission("credential.manage")
def revoke_credential(host_id: int, credential_id: int):
    HostService().revoke_credential(_host(host_id), credential_id, user=get_current_user())
    return ok({"revoked": True})


def _queue_host_operation(host, op_type: OperationType):
    from app.tasks.host_tasks import discover_host, test_ssh_connection

    ops = OperationService()
    operation = ops.create(
        op_type,
        target=host,
        user=get_current_user(),
        request_id=current_context().get("request_id"),
    )
    task = test_ssh_connection if op_type == OperationType.TEST_CONNECTION else discover_host
    result = task.delay(operation.id)
    operation.job_id = getattr(result, "id", None)
    from app.extensions import db

    db.session.commit()
    db.session.refresh(operation)
    return operation


@api.post("/hosts/<int:host_id>/test-connection")
@require_permission("host.test")
def test_connection(host_id: int):
    operation = _queue_host_operation(_host(host_id), OperationType.TEST_CONNECTION)
    return accepted(operation.to_dict(), poll=f"/api/operations/{operation.id}")


@api.post("/hosts/<int:host_id>/discover")
@require_permission("host.test")
def discover(host_id: int):
    operation = _queue_host_operation(_host(host_id), OperationType.DISCOVER)
    return accepted(operation.to_dict(), poll=f"/api/operations/{operation.id}")


@api.post("/hosts/<int:host_id>/refresh-status")
@require_permission("host.test")
def refresh_status(host_id: int):
    operation = _queue_host_operation(_host(host_id), OperationType.TEST_CONNECTION)
    return accepted(operation.to_dict(), poll=f"/api/operations/{operation.id}")


@api.post("/hosts/<int:host_id>/host-key/scan")
@require_permission("host.approve_key")
def scan_host_key(host_id: int):
    return ok(HostKeyService().scan(_host(host_id), user=get_current_user()))


@api.post("/hosts/<int:host_id>/host-key/approve")
@require_permission("host.approve_key")
def approve_host_key(host_id: int):
    data = json_body()
    host = HostKeyService().approve(
        _host(host_id), str(data.get("fingerprint", "")), user=get_current_user()
    )
    return ok(host.to_dict(include_system=False))


@api.post("/hosts/<int:host_id>/host-key/revoke")
@require_permission("host.approve_key")
def revoke_host_key(host_id: int):
    data = json_body(required=False)
    host = HostKeyService().revoke(
        _host(host_id), user=get_current_user(), reason=str(data.get("reason", ""))
    )
    return ok(host.to_dict(include_system=False))


@api.post("/hosts/<int:host_id>/reconcile")
@require_permission("lifecycle.status")
def reconcile_host(host_id: int):
    from app.tasks.maintenance_tasks import reconcile_host as task

    host = _host(host_id)
    result = task.delay(host.id)
    return accepted({"job_id": getattr(result, "id", None), "host_id": host.id})


@api.get("/hosts/<int:host_id>/instances")
@require_permission("host.view")
def host_instances(host_id: int):
    return ok([i.to_dict() for i in InstanceRepository().for_host(_host(host_id).id)])


@api.get("/hosts/<int:host_id>/requirements")
@require_permission("host.view")
def host_requirements(host_id: int):
    host = _host(host_id)
    return ok(
        ProductionGuard(get_settings_service()).requirements(host.environment).to_dict()
        | {"enabled": parse_bool(host.enabled)}
    )
