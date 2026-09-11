"""Lifecycle operation records: creation, progress logging and completion."""

from __future__ import annotations

from typing import Any

from app.config.logging import get_logger, redact
from app.errors import ScarletError
from app.extensions import db
from app.models.enums import OperationStatus, OperationType
from app.models.lifecycle import LifecycleOperation, OperationLog
from app.repositories import OperationRepository
from app.ssh.result import CommandResult, truncate_output
from app.utils.ids import new_reference
from app.utils.time import duration_seconds, utcnow

log = get_logger(__name__)


class OperationRecorder:
    """Callable passed to runtime adapters as ``ctx.log``; persists OperationLog rows."""

    def __init__(self, operation: LifecycleOperation) -> None:
        self.operation = operation

    def __call__(self, level: str, message: str, result: CommandResult | None = None) -> None:
        entry = OperationLog(
            operation_id=self.operation.id,
            timestamp=utcnow(),
            level=level.upper()[:8],
            message=redact(str(message))[:4000],
        )
        if result is not None:
            entry.command = redact(result.command)[:4000]
            entry.exit_code = result.exit_code
            entry.stdout = redact(truncate_output(result.stdout, 64 * 1024))
            entry.stderr = redact(truncate_output(result.stderr, 64 * 1024))
            entry.duration_seconds = result.duration_seconds
        db.session.add(entry)
        db.session.flush()


class OperationService:
    def __init__(self) -> None:
        self.repo = OperationRepository()

    def create(
        self,
        operation_type: OperationType | str,
        *,
        application=None,
        target=None,
        instance=None,
        deployment=None,
        user=None,
        reason: str = "",
        request_id: str | None = None,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
    ) -> LifecycleOperation:
        op_type = (
            operation_type.value
            if isinstance(operation_type, OperationType)
            else str(operation_type).upper()
        )
        operation = LifecycleOperation(
            reference="pending",
            operation_type=op_type,
            status=OperationStatus.QUEUED.value,
            application_id=getattr(application, "id", None),
            target_id=getattr(target, "id", None),
            instance_id=getattr(instance, "id", None),
            deployment_id=getattr(deployment, "id", None),
            environment_code=(
                target.environment.code
                if target is not None and getattr(target, "environment", None)
                else None
            ),
            requested_by_id=getattr(user, "id", None),
            reason=(reason or "")[:2000],
            request_id=request_id,
            parameters=parameters or {},
            timeout_seconds=timeout_seconds,
        )
        db.session.add(operation)
        db.session.flush()
        operation.reference = new_reference("OP", operation.id)
        db.session.commit()
        return operation

    def mark_running(self, operation: LifecycleOperation, job_id: str | None = None) -> None:
        operation.status = OperationStatus.RUNNING.value
        operation.started_at = utcnow()
        if job_id:
            operation.job_id = job_id
        db.session.commit()

    def mark_success(
        self,
        operation: LifecycleOperation,
        result: dict[str, Any] | None = None,
        result_code: str | None = None,
    ) -> None:
        operation.status = OperationStatus.SUCCESS.value
        operation.completed_at = utcnow()
        operation.duration_seconds = duration_seconds(
            operation.started_at or operation.created_at, operation.completed_at
        )
        operation.result = result or {}
        operation.result_code = result_code
        db.session.commit()

    def mark_failed(
        self, operation: LifecycleOperation, exc: Exception, *, timeout: bool = False
    ) -> None:
        operation.status = (OperationStatus.TIMEOUT if timeout else OperationStatus.FAILED).value
        operation.completed_at = utcnow()
        operation.duration_seconds = duration_seconds(
            operation.started_at or operation.created_at, operation.completed_at
        )
        if isinstance(exc, ScarletError):
            operation.error_code = exc.code
            operation.error_message = redact(exc.message)[:4000]
            details = dict(exc.details or {})
            if hasattr(exc, "stderr") and getattr(exc, "stderr", None):
                details["stderr"] = redact(str(exc.stderr))[:4000]
            operation.result = {"error_details": details}
        else:
            operation.error_code = "INTERNAL_ERROR"
            operation.error_message = (
                "An internal error occurred. See server logs (request id in details)."
            )
            log.exception("operation %s failed with unexpected error", operation.reference)
        db.session.commit()

    def cancel(self, operation: LifecycleOperation, *, user=None) -> LifecycleOperation:
        if operation.status_enum.is_terminal:
            return operation
        operation.status = OperationStatus.CANCELLED.value
        operation.completed_at = utcnow()
        db.session.commit()
        return operation

    def recorder(self, operation: LifecycleOperation) -> OperationRecorder:
        return OperationRecorder(operation)

    def logs_text(self, operation: LifecycleOperation) -> str:
        lines = []
        for entry in operation.logs:
            lines.append(f"{entry.timestamp.isoformat()} [{entry.level}] {entry.message}")
            if entry.command:
                lines.append(f"    $ {entry.command}")
            if entry.exit_code is not None:
                lines.append(f"    exit={entry.exit_code} duration={entry.duration_seconds}s")
            if entry.stdout:
                lines.extend("    | " + line for line in entry.stdout.splitlines()[:200])
            if entry.stderr:
                lines.extend("    ! " + line for line in entry.stderr.splitlines()[:200])
        return "\n".join(lines) + "\n"
