"""Lifecycle operations (START/STOP/RESTART/STATUS/HEALTH/LOGS/VERSION/SCALE).

``request`` validates, applies PROD safety and queues a background job.
``execute`` is called by the worker (or synchronously for read-only queries)
and performs the operation through the runtime adapter under a lock.
"""

from __future__ import annotations

from typing import Any

from flask import current_app

from app.audit import audit
from app.config.logging import bind_context, current_context, reset_context
from app.deployment.domain import compute_drift
from app.deployment.planner import build_desired_state
from app.deployment.remote_layout import RemoteLayout
from app.errors import ConflictError, NotFoundError, ScarletError, ValidationError
from app.extensions import db
from app.lifecycle.health import HealthChecker, health_spec_from_application
from app.lifecycle.locks import get_lock_manager, runtime_lock_key
from app.models.enums import (
    ApplicationState,
    AuditResult,
    DesiredState,
    HealthStatus,
    NotificationLevel,
    OperationStatus,
    OperationType,
    RuntimeType,
)
from app.models.lifecycle import HealthCheck, LifecycleOperation
from app.repositories import (
    ApplicationRepository,
    HostRepository,
    InstanceRepository,
    OperationRepository,
)
from app.runtimes.base import HostInfo, RuntimeContext
from app.runtimes.factory import RuntimeFactory
from app.security.crypto import get_cipher
from app.security.prod_guard import ProductionGuard
from app.security.validators import validate_int_range, validate_log_search
from app.services.configuration_service import ConfigurationService
from app.services.notification_service import notify_operators
from app.services.operation_service import OperationService
from app.services.settings_service import get_settings_service
from app.ssh.factory import get_ssh_factory
from app.utils.time import utcnow

MUTATING = {OperationType.START, OperationType.STOP, OperationType.RESTART, OperationType.SCALE}
READ_ONLY = {OperationType.STATUS, OperationType.HEALTH, OperationType.LOGS, OperationType.VERSION}
PERMISSION_FOR = {
    OperationType.START: "lifecycle.start",
    OperationType.STOP: "lifecycle.stop",
    OperationType.RESTART: "lifecycle.restart",
    OperationType.SCALE: "lifecycle.restart",
    OperationType.STATUS: "lifecycle.status",
    OperationType.HEALTH: "health.execute",
    OperationType.LOGS: "logs.view",
    OperationType.VERSION: "application.view",
}
AUDIT_FOR = {
    OperationType.START: "APPLICATION_STARTED",
    OperationType.STOP: "APPLICATION_STOPPED",
    OperationType.RESTART: "APPLICATION_RESTARTED",
    OperationType.SCALE: "APPLICATION_SCALED",
    OperationType.STATUS: "APPLICATION_STATUS_CHECKED",
    OperationType.HEALTH: "HEALTH_CHECK_EXECUTED",
    OperationType.LOGS: "LOGS_VIEWED",
    OperationType.VERSION: "VERSION_CHECKED",
}


class LifecycleService:
    def __init__(self) -> None:
        self.apps = ApplicationRepository()
        self.hosts = HostRepository()
        self.instances = InstanceRepository()
        self.operations = OperationService()
        self.op_repo = OperationRepository()
        self.config = ConfigurationService()
        self.guard = ProductionGuard(get_settings_service())

    # --- request (API/web layer) -----------------------------------------------------------------
    def request(
        self,
        operation_type: str,
        *,
        application_id: int,
        host_id: int,
        user=None,
        reason: str = "",
        confirmation: str | None = None,
        parameters: dict[str, Any] | None = None,
        sync: bool = False,
    ) -> LifecycleOperation:
        op_type = OperationType.parse(operation_type)
        if op_type is None or op_type not in MUTATING | READ_ONLY:
            raise ValidationError(
                "Unsupported operation.",
                errors={
                    "operation": [
                        f"Must be one of {', '.join(o.value for o in MUTATING | READ_ONLY)}"
                    ]
                },
            )
        application = self.apps.get_or_404(application_id, "Application")
        host = self.hosts.get_or_404(host_id, "Host")
        self.guard.authorize(PERMISSION_FOR[op_type], host.environment, user=user)
        if op_type in MUTATING:
            self.guard.check_operation(
                environment=host.environment,
                operation=op_type.value,
                confirmation=confirmation,
                reason=reason,
            )
        if not host.enabled:
            raise ValidationError(f"Host {host.name} is disabled.")
        instance = self.instances.get_for(application.id, host.id)
        if instance is None or instance.current_version_id is None:
            raise NotFoundError(f"{application.name} has never been deployed to {host.name}.")
        params = self._validate_parameters(op_type, parameters or {})
        if op_type in MUTATING and get_lock_manager().is_locked(
            runtime_lock_key(host.id, application.id)
        ):
            raise ConflictError(
                "Another operation is running on this application/target. Wait for it to finish."
            )
        operation = self.operations.create(
            op_type,
            application=application,
            target=host,
            instance=instance,
            user=user,
            reason=reason,
            request_id=current_context().get("request_id"),
            parameters=params,
            timeout_seconds=int(current_app.config.get("SCARLET_SSH_COMMAND_TIMEOUT", 600)),
        )
        if sync and op_type in READ_ONLY:
            self.execute(operation.id)
            db.session.refresh(operation)
            return operation
        from app.tasks.lifecycle_tasks import run_lifecycle_operation

        result = run_lifecycle_operation.delay(operation.id)
        operation.job_id = getattr(result, "id", None)
        db.session.commit()
        return operation

    @staticmethod
    def _validate_parameters(op_type: OperationType, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if op_type == OperationType.LOGS:
            out["lines"] = validate_int_range(
                params.get("lines", 200), field="lines", minimum=1, maximum=5000, default=200
            )
            since = (params.get("since") or "").strip()
            if since:
                import re

                if not re.fullmatch(r"\d{1,5}[smh]", since):
                    raise ValidationError(
                        "Invalid 'since' (use 10m, 2h).", errors={"since": ["Use 10m, 2h."]}
                    )
                out["since"] = since
            out["search"] = validate_log_search(params.get("search"))
        if op_type == OperationType.SCALE:
            out["replicas"] = validate_int_range(
                params.get("replicas"), field="replicas", minimum=0, maximum=100
            )
        if op_type == OperationType.HEALTH:
            retries = params.get("retries")
            if retries not in (None, ""):
                out["retries"] = validate_int_range(retries, field="retries", minimum=1, maximum=50)
        return out

    # --- execution (worker) ----------------------------------------------------------------------------
    def execute(self, operation_id: int, job_id: str | None = None) -> LifecycleOperation:
        operation = db.session.get(LifecycleOperation, operation_id)
        if operation is None:
            raise NotFoundError(f"Operation {operation_id} not found.")
        if operation.status_enum.is_terminal:
            return operation
        op_type = OperationType(operation.operation_type)
        token = bind_context(
            operation_id=operation.reference,
            application_id=operation.application_id,
            target_id=operation.target_id,
            request_id=operation.request_id,
            job_id=job_id,
        )
        self.operations.mark_running(operation, job_id)
        try:
            if op_type in MUTATING:
                with get_lock_manager().hold(
                    runtime_lock_key(operation.target_id, operation.application_id),
                    ttl=int(current_app.config.get("SCARLET_LOCK_TIMEOUT", 1800)),
                    description=f"{operation.operation_type} {operation.application.code} on {operation.target.name}",
                ):
                    result, code = self._perform(operation, op_type)
            else:
                result, code = self._perform(operation, op_type)
            self.operations.mark_success(operation, result, code)
            if op_type in MUTATING:
                audit.record(
                    AUDIT_FOR[op_type],
                    user=operation.requested_by,
                    entity_type="LifecycleOperation",
                    entity_id=operation.id,
                    application=operation.application,
                    target=operation.target,
                    details={
                        "reference": operation.reference,
                        "result_code": code,
                        "reason": operation.reason,
                    },
                )
            elif op_type == OperationType.LOGS:
                audit.record(
                    AUDIT_FOR[op_type],
                    user=operation.requested_by,
                    entity_type="LifecycleOperation",
                    entity_id=operation.id,
                    application=operation.application,
                    target=operation.target,
                    result=AuditResult.INFO,
                    details={"lines": operation.parameters.get("lines")},
                )
        except ScarletError as exc:
            self.operations.mark_failed(
                operation, exc, timeout=exc.code in {"SSH_TIMEOUT", "OPERATION_TIMEOUT"}
            )
            if op_type in MUTATING:
                audit.record(
                    AUDIT_FOR[op_type],
                    user=operation.requested_by,
                    entity_type="LifecycleOperation",
                    entity_id=operation.id,
                    application=operation.application,
                    target=operation.target,
                    result=AuditResult.FAILURE,
                    details={
                        "reference": operation.reference,
                        "error": exc.message,
                        "code": exc.code,
                    },
                )
                notify_operators(
                    "OPERATION_FAILED",
                    f"{op_type.value} failed for {operation.application.code}",
                    f"{operation.reference} on {operation.target.name}: {exc.message}",
                    level=NotificationLevel.ERROR,
                    link=f"/operations/{operation.id}",
                )
        except Exception as exc:  # noqa: BLE001
            self.operations.mark_failed(operation, exc)
        finally:
            reset_context(token)
        return operation

    def _context(self, operation: LifecycleOperation):
        host = operation.target
        application = operation.application
        base = host.remote_base_path or current_app.config["SCARLET_REMOTE_BASE_PATH"]
        info = HostInfo(
            name=host.name,
            runtime_type=host.runtime_type,
            base_path=base,
            rootless=host.runtime_rootless,
            kubernetes_namespace=host.kubernetes_namespace,
            kubernetes_context=host.kubernetes_context,
        )
        if (
            host.runtime_type == RuntimeType.KUBERNETES.value
            and host.kubernetes_credential is not None
        ):
            info.kubeconfig = get_cipher().decrypt(host.kubernetes_credential.encrypted_secret)
        client = get_ssh_factory().connect(host)
        ctx = RuntimeContext(
            executor=client,
            host=info,
            application_code=application.code,
            layout=RemoteLayout(base, application.code),
            log=self.operations.recorder(operation),
            timeout=operation.timeout_seconds or 600,
        )
        return client, ctx, RuntimeFactory.get(host.runtime_type)

    def _perform(
        self, operation: LifecycleOperation, op_type: OperationType
    ) -> tuple[dict[str, Any], str]:
        instance = operation.instance or self.instances.get_for(
            operation.application_id, operation.target_id
        )
        if instance is None or instance.current_version is None:
            raise NotFoundError("Application is not deployed on this host.")
        application, host, version = (
            operation.application,
            operation.target,
            instance.current_version,
        )
        env_vars, _ = self.config.render_environment(
            application, host.environment, version.manifest or {}
        )
        desired = build_desired_state(application, version, host, env_vars)
        client, ctx, adapter = self._context(operation)
        try:
            if op_type == OperationType.START:
                instance.desired_state = DesiredState.RUNNING.value
                instance.desired_updated_at = utcnow()
                actual = adapter.start(ctx, desired)
                self._store_actual(instance, actual)
                return actual.to_dict(), (
                    "ALREADY_RUNNING" if actual.message == "ALREADY_RUNNING" else "STARTED"
                )
            if op_type == OperationType.STOP:
                instance.desired_state = DesiredState.STOPPED.value
                instance.desired_updated_at = utcnow()
                actual = adapter.stop(ctx)
                self._store_actual(instance, actual)
                return actual.to_dict(), (
                    "ALREADY_STOPPED" if actual.message == "ALREADY_STOPPED" else "STOPPED"
                )
            if op_type == OperationType.RESTART:
                instance.desired_state = DesiredState.RUNNING.value
                actual = adapter.restart(ctx, desired)
                self._store_actual(instance, actual)
                return actual.to_dict(), "RESTARTED"
            if op_type == OperationType.SCALE:
                replicas = int(operation.parameters.get("replicas", 1))
                if not adapter.supports_scaling:
                    raise ValidationError(f"{host.runtime_type} does not support scaling.")
                instance.desired_replicas = replicas
                instance.desired_state = (
                    DesiredState.RUNNING if replicas > 0 else DesiredState.STOPPED
                ).value
                actual = adapter.scale(ctx, replicas)
                self._store_actual(instance, actual)
                return actual.to_dict(), "SCALED"
            if op_type == OperationType.STATUS:
                actual = adapter.status(ctx)
                self._store_actual(instance, actual, detect_drift=desired)
                data = actual.to_dict()
                data["inspect"] = adapter.inspect(ctx)
                data["drift"] = compute_drift(
                    (
                        desired
                        if instance.desired_state != DesiredState.STOPPED.value
                        else desired.__class__(
                            **{**desired.__dict__, "state": DesiredState.STOPPED}
                        )
                    ),
                    actual,
                ).to_dict()
                return data, actual.state.value
            if op_type == OperationType.VERSION:
                version_seen = adapter.version(ctx)
                actual = adapter.status(ctx)
                self._store_actual(instance, actual, detect_drift=desired)
                return {
                    "version": version_seen,
                    "recorded_version": version.version,
                    "match": version_seen == version.version,
                    "previous_version": (
                        instance.previous_version.version if instance.previous_version else None
                    ),
                }, ("MATCH" if version_seen == version.version else "MISMATCH")
            if op_type == OperationType.HEALTH:
                spec = health_spec_from_application(application, version.manifest)
                result = HealthChecker(adapter).check(
                    ctx, spec, desired, retries=operation.parameters.get("retries")
                )
                db.session.add(
                    HealthCheck(
                        instance_id=instance.id,
                        check_type=spec.check_type,
                        status=result.status.value,
                        checked_at=utcnow(),
                        duration_seconds=result.duration_seconds,
                        attempts=result.attempts,
                        message=result.message[:2000],
                        details=result.details,
                        operation_id=operation.id,
                    )
                )
                previous_status = instance.health_status
                instance.health_status = result.status.value
                instance.last_health_check_at = utcnow()
                instance.last_health_message = result.message[:2000]
                db.session.commit()
                if not result.healthy:
                    audit.record(
                        "HEALTH_CHECK_FAILED",
                        user=operation.requested_by,
                        entity_type="ApplicationInstance",
                        entity_id=instance.id,
                        application=application,
                        target=host,
                        result=AuditResult.FAILURE,
                        details={"message": result.message, "attempts": result.attempts},
                    )
                    if previous_status != HealthStatus.UNHEALTHY.value:
                        notify_operators(
                            "HEALTH_FAILED",
                            f"{application.code} unhealthy on {host.name}",
                            result.message,
                            level=NotificationLevel.ERROR,
                            link=f"/applications/{application.id}",
                            email=True,
                        )
                return result.to_dict(), result.status.value
            if op_type == OperationType.LOGS:
                lines = int(operation.parameters.get("lines", 200))
                chunk = adapter.logs(ctx, lines=lines, since=operation.parameters.get("since"))
                search = operation.parameters.get("search")
                out_lines = [
                    line for line in chunk.lines if not search or search.lower() in line.lower()
                ]
                return {
                    "lines": out_lines,
                    "count": len(out_lines),
                    "source": chunk.source,
                    "truncated": chunk.truncated,
                    "search": search,
                }, "OK"
            raise ValidationError("Unsupported operation.")
        finally:
            ctx.host.kubeconfig = None
            client.close()

    def _store_actual(self, instance, actual, detect_drift=None) -> None:
        instance.actual_state = actual.state.value
        if actual.version:
            instance.actual_version = actual.version
        instance.actual_replicas = actual.replicas
        instance.actual_runtime = actual.runtime
        instance.actual_details = actual.details
        instance.actual_observed_at = utcnow()
        instance.last_operation_at = utcnow()
        if actual.health != HealthStatus.UNKNOWN:
            instance.health_status = actual.health.value
        if detect_drift is not None:
            desired = detect_drift
            if instance.desired_state == DesiredState.STOPPED.value:
                desired = desired.__class__(**{**desired.__dict__, "state": DesiredState.STOPPED})
            drift = compute_drift(desired, actual)
            instance.drift_detected = drift.detected
            instance.drift_type = drift.drift_type.value
            instance.drift_details = drift.details if drift.detected else None
            instance.drift_detected_at = utcnow() if drift.detected else None
        elif actual.state in {ApplicationState.RUNNING, ApplicationState.STOPPED}:
            instance.drift_detected = False
            instance.drift_type = "NONE"
            instance.drift_details = None
        db.session.commit()

    # --- read helpers --------------------------------------------------------------------------------------
    def get(self, operation_id: int) -> LifecycleOperation:
        operation = self.op_repo.get(operation_id)
        if operation is None:
            raise NotFoundError(f"Operation {operation_id} not found.")
        return operation

    def instance_for(self, application_id: int, host_id: int):
        instance = self.instances.get_for(application_id, host_id)
        if instance is None:
            raise NotFoundError("Application is not deployed on this host.")
        return instance

    def cancel(self, operation: LifecycleOperation, *, user=None) -> LifecycleOperation:
        if operation.status != OperationStatus.QUEUED.value:
            raise ConflictError("Only queued operations can be cancelled.")
        self.operations.cancel(operation, user=user)
        audit.record(
            "OPERATION_CANCELLED",
            user=user,
            entity_type="LifecycleOperation",
            entity_id=operation.id,
            application=operation.application,
            target=operation.target,
        )
        return operation
