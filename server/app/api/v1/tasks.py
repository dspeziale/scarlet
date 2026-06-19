"""
/api/v1/tasks  — task scheduling, dispatch to probes, result retrieval.
"""

from flask import g, jsonify, request
from sqlalchemy import select

from app.api.v1 import api_v1_bp
from app.auth.rbac import require_role, TENANT_ADMIN, OPERATOR, SUPERADMIN
from app.extensions import db
from app.models.task import Task, TaskAssignment, TaskResult
from app.services.task_service import TaskService

import structlog
log = structlog.get_logger(__name__)

_svc = TaskService()


def _task_row(task: Task) -> dict:
    """Task dict enriched with first assignment info for the UI."""
    d = task.to_dict()
    assignment = db.session.execute(
        select(TaskAssignment)
        .where(TaskAssignment.task_id == task.id)
        .order_by(TaskAssignment.assigned_at)
        .limit(1)
    ).scalar_one_or_none()
    if assignment:
        d["assignment_id"] = assignment.id
        d["probe_id"] = assignment.probe_id
        d["assignment_status"] = assignment.status
        d["completed_at"] = assignment.completed_at.isoformat() if assignment.completed_at else None
        # Attach probe hostname if available
        from app.models.probe import Probe
        p = db.session.get(Probe, assignment.probe_id)
        d["probe_hostname"] = p.hostname if p else assignment.probe_id
    else:
        d["assignment_id"] = None
        d["probe_id"] = None
        d["probe_hostname"] = None
        d["assignment_status"] = None
        d["completed_at"] = None
    return d


# ── User-facing: task management ───────────────────────────────────────────

@api_v1_bp.get("/tasks")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def list_tasks():
    """List tasks with assignment info. Superadmin sees all tenants."""
    user = g.current_user
    status = request.args.get("status")
    probe_id = request.args.get("probe_id")

    if user.is_superadmin:
        tenant_id = request.args.get("tenant_id")
        if tenant_id:
            tasks = _svc.list_tasks(tenant_id, status=status)
        else:
            stmt = select(Task).order_by(Task.created_at.desc()).limit(200)
            if status:
                stmt = stmt.where(Task.status == status)
            tasks = list(db.session.execute(stmt).scalars())
    else:
        tasks = _svc.list_tasks(user.tenant_id, status=status)

    rows = [_task_row(t) for t in tasks]

    if probe_id:
        rows = [r for r in rows if r.get("probe_id") == probe_id]

    return jsonify(rows), 200


@api_v1_bp.post("/tasks")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def create_task():
    user = g.current_user
    body = request.get_json(silent=True) or {}
    task_type = body.get("task_type")
    if not task_type:
        return jsonify(error="validation_error", message="task_type required"), 400

    tenant_id = (body.get("tenant_id") or user.tenant_id) if user.is_superadmin else user.tenant_id
    if not tenant_id:
        return jsonify(error="validation_error", message="tenant_id required"), 400

    try:
        task = _svc.create_task(
            tenant_id=tenant_id,
            created_by=user.id,
            task_type=task_type,
            parameters=body.get("parameters") or {},
            name=body.get("name"),
            description=body.get("description"),
            priority=int(body.get("priority", 5)),
        )
        return jsonify(task.to_dict()), 201
    except ValueError as e:
        return jsonify(error="validation_error", message=str(e)), 400


@api_v1_bp.post("/tasks/dispatch")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def dispatch_task():
    """Create a task and immediately assign it to a probe (single operation)."""
    user = g.current_user
    body = request.get_json(silent=True) or {}

    probe_id = body.get("probe_id")
    task_type = body.get("task_type")
    if not probe_id or not task_type:
        return jsonify(error="validation_error", message="probe_id and task_type required"), 400

    # Verify probe exists first
    from app.models.probe import Probe
    probe = db.session.get(Probe, probe_id)
    if not probe:
        return jsonify(error="not_found", message="Probe not found"), 404

    # For superadmin: if tenant_id not provided, inherit from the probe
    if user.is_superadmin:
        tenant_id = body.get("tenant_id") or probe.tenant_id
    else:
        tenant_id = user.tenant_id

    if not tenant_id:
        return jsonify(error="validation_error", message="tenant_id required"), 400

    if not probe or (not user.is_superadmin and probe.tenant_id != tenant_id):
        return jsonify(error="not_found", message="Probe not found"), 404
    if not probe.enabled:
        return jsonify(error="forbidden", message="Probe is disabled"), 403

    try:
        task = _svc.create_task(
            tenant_id=tenant_id,
            created_by=user.id,
            task_type=task_type,
            parameters=body.get("parameters") or {},
            name=body.get("name") or f"{task_type} on {probe.hostname}",
            priority=int(body.get("priority", 5)),
        )
        assignment = _svc.assign_task(task.id, probe_id, tenant_id)
        return jsonify({
            "task_id": task.id,
            "assignment_id": assignment.id,
            "task_type": task_type,
            "probe_hostname": probe.hostname,
            "status": assignment.status,
        }), 201
    except ValueError as e:
        return jsonify(error="error", message=str(e)), 400


@api_v1_bp.get("/tasks/<task_id>")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def get_task(task_id: str):
    user = g.current_user
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify(error="not_found"), 404
    if not user.is_superadmin and task.tenant_id != user.tenant_id:
        return jsonify(error="forbidden"), 403
    return jsonify(_task_row(task)), 200


@api_v1_bp.get("/tasks/<task_id>/result")
@require_role(SUPERADMIN, TENANT_ADMIN, OPERATOR)
def get_task_result(task_id: str):
    """Return the result(s) for a task."""
    user = g.current_user
    task = db.session.get(Task, task_id)
    if not task:
        return jsonify(error="not_found"), 404
    if not user.is_superadmin and task.tenant_id != user.tenant_id:
        return jsonify(error="forbidden"), 403

    results = list(db.session.execute(
        select(TaskResult)
        .where(TaskResult.task_id == task_id)
        .order_by(TaskResult.received_at.desc())
    ).scalars())
    return jsonify([r.to_dict() for r in results]), 200


@api_v1_bp.post("/tasks/<task_id>/assign")
@require_role(SUPERADMIN, TENANT_ADMIN)
def assign_task(task_id: str):
    body = request.get_json(silent=True) or {}
    probe_id = body.get("probe_id")
    if not probe_id:
        return jsonify(error="validation_error", message="probe_id required"), 400
    user = g.current_user
    tenant_id = body.get("tenant_id") if user.is_superadmin else user.tenant_id
    if not tenant_id:
        return jsonify(error="validation_error", message="tenant_id required"), 400
    try:
        assignment = _svc.assign_task(task_id, probe_id, tenant_id)
        return jsonify({"assignment_id": assignment.id, "status": assignment.status}), 200
    except ValueError as e:
        return jsonify(error="error", message=str(e)), 400


@api_v1_bp.delete("/tasks/<task_id>")
@require_role(SUPERADMIN, TENANT_ADMIN)
def cancel_task(task_id: str):
    user = g.current_user
    tenant_id = user.tenant_id
    try:
        _svc.cancel_task(task_id, tenant_id)
        return jsonify(message="Task cancelled"), 200
    except ValueError as e:
        return jsonify(error="error", message=str(e)), 400
