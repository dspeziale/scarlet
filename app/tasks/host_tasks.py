"""Host jobs: test connection and discovery (recorded as lifecycle operations)."""

from __future__ import annotations

from app.config.logging import get_logger
from app.errors import ScarletError
from app.extensions import db
from app.models.enums import OperationType
from app.models.host import TargetHost
from app.models.lifecycle import LifecycleOperation
from app.tasks.celery_app import celery, retry_policy

log = get_logger(__name__)


def _run_host_operation(self, operation_id: int, op_type: OperationType) -> dict:
    from app.services.host_service import HostService
    from app.services.operation_service import OperationService

    ops = OperationService()
    operation = db.session.get(LifecycleOperation, operation_id)
    if operation is None:
        return {"ok": False, "error": "operation not found"}
    if operation.status_enum.is_terminal:
        return {"ok": True, "skipped": True}
    host = db.session.get(TargetHost, operation.target_id)
    ops.mark_running(operation, self.request.id)
    try:
        service = HostService()
        if op_type == OperationType.TEST_CONNECTION:
            result = service.test_connection(host, user=operation.requested_by)
            ops.mark_success(operation, result, "ONLINE")
        else:
            result = service.discover(host, user=operation.requested_by)
            ops.mark_success(
                operation,
                {
                    "os": result.get("os"),
                    "architecture": result.get("architecture"),
                    "cpu_count": result.get("cpu_count"),
                    "memory": result.get("memory"),
                    "disk": result.get("disk"),
                    "runtimes": result.get("runtimes"),
                    "selinux": result.get("selinux"),
                    "suggested_runtime": result.get("suggested_runtime"),
                },
                "DISCOVERED",
            )
        return {"ok": True, "status": operation.status}
    except ScarletError as exc:
        db.session.rollback()
        operation = db.session.get(LifecycleOperation, operation_id)
        if retry_policy(exc) and self.request.retries < self.max_retries:
            operation.retries += 1
            operation.status = "QUEUED"
            db.session.commit()
            raise self.retry(exc=exc, countdown=min(60, 5 * (2**self.request.retries))) from exc
        ops.mark_failed(operation, exc)
        return {"ok": False, "status": operation.status, "error": exc.message, "code": exc.code}
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log.exception("host task crashed")
        operation = db.session.get(LifecycleOperation, operation_id)
        ops.mark_failed(operation, exc)
        return {"ok": False, "error": "internal error"}


@celery.task(bind=True, name="scarlet.host.test_ssh_connection", max_retries=2)
def test_ssh_connection(self, operation_id: int) -> dict:
    return _run_host_operation(self, operation_id, OperationType.TEST_CONNECTION)


@celery.task(bind=True, name="scarlet.host.discover_host", max_retries=2)
def discover_host(self, operation_id: int) -> dict:
    return _run_host_operation(self, operation_id, OperationType.DISCOVER)
