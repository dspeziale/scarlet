"""Lifecycle operation endpoints (job polling, logs, cancel) and job status."""

from __future__ import annotations

from flask import Response, request

from app.api import api
from app.api.responses import list_params, ok, paged
from app.repositories import OperationRepository
from app.security.rbac import get_current_user, require_permission
from app.services.lifecycle_service import LifecycleService
from app.services.operation_service import OperationService


@api.get("/operations")
@require_permission("deployment.view")
def list_operations():
    params = list_params(default_sort="created_at")
    page = OperationRepository().list(
        **params,
        status=request.args.get("status") or None,
        operation_type=request.args.get("type") or None,
        application_id=request.args.get("application_id") or None,
        target_id=request.args.get("host_id") or None,
        environment=request.args.get("environment") or None,
        date_from=request.args.get("date_from") or None,
        date_to=request.args.get("date_to") or None,
    )
    return paged(page)


@api.get("/operations/active")
@require_permission("deployment.view")
def active_operations():
    return ok([o.to_dict() for o in OperationRepository().active()])


@api.get("/operations/<int:operation_id>")
@require_permission("deployment.view")
def get_operation(operation_id: int):
    operation = LifecycleService().get(operation_id)
    include_logs = request.args.get("logs", "true").lower() != "false"
    data = operation.to_dict(include_logs=include_logs)
    if operation.operation_type == "LOGS" and not get_current_user().has_permission("logs.view"):
        data["result"] = {}
    return ok(data)


@api.post("/operations/<int:operation_id>/cancel")
@require_permission("deployment.cancel")
def cancel_operation(operation_id: int):
    operation = LifecycleService().cancel(
        LifecycleService().get(operation_id), user=get_current_user()
    )
    return ok(operation.to_dict())


@api.get("/operations/<int:operation_id>/download")
@require_permission("logs.download")
def download_operation_log(operation_id: int):
    operation = LifecycleService().get(operation_id)
    body = OperationService().logs_text(operation)
    if operation.operation_type == "LOGS" and operation.result:
        body += "\n--- application log lines ---\n" + "\n".join(operation.result.get("lines", []))
    return Response(
        body,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{operation.reference}.log"'},
    )


@api.get("/jobs/<job_id>")
@require_permission("deployment.view")
def job_status(job_id: str):
    """Celery job status plus the SCARLET record that owns it (deployment or operation)."""
    from app.extensions import db
    from app.models.deployment import Deployment
    from app.models.lifecycle import LifecycleOperation
    from app.tasks.celery_app import celery

    if len(job_id) > 64 or not job_id.replace("-", "").isalnum():
        from app.errors import ValidationError

        raise ValidationError("Invalid job id.")
    payload = {"job_id": job_id, "state": None, "deployment": None, "operation": None}
    try:
        payload["state"] = celery.AsyncResult(job_id).state
    except Exception:  # noqa: BLE001 - broker unavailable
        payload["state"] = "UNKNOWN"
    deployment = (
        db.session.execute(db.select(Deployment).where(Deployment.job_id == job_id))
        .scalars()
        .first()
    )
    if deployment is not None:
        payload["deployment"] = deployment.to_dict()
    operation = (
        db.session.execute(db.select(LifecycleOperation).where(LifecycleOperation.job_id == job_id))
        .scalars()
        .first()
    )
    if operation is not None:
        payload["operation"] = operation.to_dict()
    return ok(payload)
