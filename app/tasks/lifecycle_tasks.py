"""Lifecycle operation jobs (start/stop/restart/status/health/logs/version/scale)."""

from __future__ import annotations

from celery.exceptions import SoftTimeLimitExceeded

from app.config.logging import get_logger
from app.errors import OperationTimeoutError, ScarletError
from app.extensions import db
from app.models.enums import OperationStatus
from app.models.lifecycle import LifecycleOperation
from app.tasks.celery_app import celery, retry_policy

log = get_logger(__name__)


@celery.task(bind=True, name="scarlet.lifecycle.run_operation", max_retries=2)
def run_lifecycle_operation(self, operation_id: int) -> dict:
    from app.services.lifecycle_service import LifecycleService
    from app.services.operation_service import OperationService

    operation = db.session.get(LifecycleOperation, operation_id)
    if operation is None:
        return {"ok": False, "error": "operation not found"}
    if operation.status_enum.is_terminal:
        return {"ok": True, "status": operation.status, "skipped": True}
    try:
        operation = LifecycleService().execute(operation_id, job_id=self.request.id)
    except SoftTimeLimitExceeded:
        db.session.rollback()
        operation = db.session.get(LifecycleOperation, operation_id)
        OperationService().mark_failed(
            operation, OperationTimeoutError("Worker time limit exceeded."), timeout=True
        )
    except ScarletError as exc:
        db.session.rollback()
        operation = db.session.get(LifecycleOperation, operation_id)
        if (
            retry_policy(exc)
            and self.request.retries < self.max_retries
            and operation.status != OperationStatus.SUCCESS.value
        ):
            operation.status = OperationStatus.QUEUED.value
            operation.retries += 1
            db.session.commit()
            raise self.retry(exc=exc, countdown=min(120, 10 * (2**self.request.retries))) from exc
        OperationService().mark_failed(operation, exc)
    db.session.refresh(operation)
    # transient failure recorded by execute(): retry if allowed
    if (
        operation.status == OperationStatus.FAILED.value
        and operation.error_code in {"SSH_CONNECTION_ERROR", "SSH_TIMEOUT"}
        and self.request.retries < self.max_retries
        and operation.operation_type in {"STATUS", "HEALTH", "VERSION"}
    ):
        operation.status = OperationStatus.QUEUED.value
        operation.retries += 1
        db.session.commit()
        raise self.retry(countdown=min(120, 10 * (2**self.request.retries)))
    return {
        "ok": operation.status == OperationStatus.SUCCESS.value,
        "status": operation.status,
        "reference": operation.reference,
        "result_code": operation.result_code,
    }
