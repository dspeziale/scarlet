"""Deployment endpoints (create, list, detail, approve, cancel, preflight)."""

from __future__ import annotations

from flask import request

from app.api import api
from app.api.responses import accepted, json_body, list_params, ok, paged, parse_bool
from app.errors import ValidationError
from app.models.deployment import DeploymentBatch
from app.repositories import DeploymentRepository
from app.security.rbac import get_current_user, require_permission
from app.services.deployment_service import DeploymentService


def _ints(values) -> list[int]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [v for v in values.split(",") if v.strip()]
    try:
        return [int(v) for v in values]
    except (TypeError, ValueError) as exc:
        raise ValidationError("host_ids must be integers.") from exc


@api.get("/deployments")
@require_permission("deployment.view")
def list_deployments():
    params = list_params(default_sort="created_at")
    page = DeploymentRepository().list(
        **params,
        application_id=request.args.get("application_id") or None,
        target_id=request.args.get("host_id") or None,
        environment=request.args.get("environment") or None,
        status=request.args.get("status") or None,
        date_from=request.args.get("date_from") or None,
        date_to=request.args.get("date_to") or None,
        batch_id=request.args.get("batch") or None,
        kind=(request.args.get("kind") or "").upper() or None,
    )
    return paged(page)


@api.post("/deployments/preflight")
@require_permission("deployment.execute")
def preflight():
    data = json_body()
    result = DeploymentService().preflight_for(
        application_id=int(data.get("application_id", 0)),
        version_id=int(data.get("version_id", 0)),
        host_ids=_ints(data.get("host_ids")),
        host_group_id=int(data["host_group_id"]) if data.get("host_group_id") else None,
        remote=parse_bool(data.get("remote", True), default=True),
        user=get_current_user(),
    )
    return ok(result)


@api.post("/deployments")
@require_permission("deployment.execute")
def create_deployment():
    data = json_body()
    try:
        application_id = int(data.get("application_id"))
        version_id = int(data.get("version_id"))
    except (TypeError, ValueError) as exc:
        raise ValidationError("application_id and version_id are required integers.") from exc
    batch = DeploymentService().create(
        application_id=application_id,
        version_id=version_id,
        host_ids=_ints(data.get("host_ids")),
        host_group_id=int(data["host_group_id"]) if data.get("host_group_id") else None,
        strategy=str(data.get("strategy", "SEQUENTIAL")),
        reason=str(data.get("reason", "")),
        confirmation=data.get("confirmation"),
        auto_rollback=data.get("auto_rollback"),
        max_parallel=int(data["max_parallel"]) if data.get("max_parallel") else None,
        stop_on_failure=parse_bool(data.get("stop_on_failure", True), default=True),
        user=get_current_user(),
    )
    payload = batch.to_dict()
    payload["deployments"] = [d.to_dict() for d in batch.deployments]
    return accepted(payload, poll=f"/api/deployments/batches/{batch.id}")


@api.get("/deployments/batches/<int:batch_id>")
@require_permission("deployment.view")
def get_batch(batch_id: int):
    from app.extensions import db

    batch = db.session.get(DeploymentBatch, batch_id)
    if batch is None:
        from app.errors import NotFoundError

        raise NotFoundError("Batch not found.")
    payload = batch.to_dict()
    payload["deployments"] = [d.to_dict() for d in batch.deployments]
    return ok(payload)


@api.get("/deployments/<int:deployment_id>")
@require_permission("deployment.view")
def get_deployment(deployment_id: int):
    service = DeploymentService()
    deployment = service.get(deployment_id)
    data = deployment.to_dict(include_steps=True)
    data["timeline"] = service.timeline(deployment)
    return ok(data)


@api.get("/deployments/<int:deployment_id>/steps")
@require_permission("deployment.view")
def get_steps(deployment_id: int):
    deployment = DeploymentService().get(deployment_id)
    return ok(
        {
            "status": deployment.status,
            "status_summary": deployment.status_enum.summary,
            "is_terminal": deployment.is_terminal,
            "steps": [s.to_dict() for s in deployment.steps],
            "error_message": deployment.error_message,
        }
    )


@api.post("/deployments/<int:deployment_id>/approve")
@require_permission("deployment.approve")
def approve_deployment(deployment_id: int):
    data = json_body(required=False)
    deployment = DeploymentService().approve(
        DeploymentService().get(deployment_id),
        user=get_current_user(),
        comment=str(data.get("comment", "")),
        approve=True,
    )
    return ok(deployment.to_dict())


@api.post("/deployments/<int:deployment_id>/reject")
@require_permission("deployment.approve")
def reject_deployment(deployment_id: int):
    data = json_body(required=False)
    deployment = DeploymentService().approve(
        DeploymentService().get(deployment_id),
        user=get_current_user(),
        comment=str(data.get("comment", "")),
        approve=False,
    )
    return ok(deployment.to_dict())


@api.post("/deployments/<int:deployment_id>/cancel")
@require_permission("deployment.cancel")
def cancel_deployment(deployment_id: int):
    data = json_body(required=False)
    deployment = DeploymentService().cancel(
        DeploymentService().get(deployment_id),
        user=get_current_user(),
        reason=str(data.get("reason", "")),
    )
    return ok(deployment.to_dict())


@api.get("/deployments/<int:deployment_id>/log")
@require_permission("logs.download")
def download_deployment_log(deployment_id: int):
    from flask import Response

    deployment = DeploymentService().get(deployment_id)
    lines = [
        f"SCARLET deployment {deployment.reference}",
        f"application: {deployment.application.code} version: {deployment.version.version}",
        f"target: {deployment.target.name} ({deployment.environment.code})",
        f"status: {deployment.status}",
        "",
    ]
    for step in deployment.steps:
        lines.append(
            f"=== [{step.sequence}] {step.label} :: {step.status} ({step.duration_seconds}s) ==="
        )
        if step.stdout:
            lines.append(step.stdout)
        if step.stderr:
            lines.append("--- stderr ---")
            lines.append(step.stderr)
        if step.error_message:
            lines.append(f"ERROR: {step.error_message}")
        lines.append("")
    body = "\n".join(lines)
    return Response(
        body,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{deployment.reference}.log"'},
    )
