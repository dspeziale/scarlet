"""Reconciliation: compare desired vs actual state for every instance, detect drift."""

from __future__ import annotations

from typing import Any

from flask import current_app

from app.audit import audit
from app.config.logging import get_logger
from app.deployment.domain import DesiredApplicationState, compute_drift
from app.deployment.planner import build_desired_state
from app.deployment.remote_layout import RemoteLayout
from app.errors import ScarletError
from app.extensions import db
from app.lifecycle.locks import get_lock_manager, runtime_lock_key
from app.models.enums import (
    ApplicationState,
    DesiredState,
    DriftType,
    HostStatus,
    NotificationLevel,
    RuntimeType,
)
from app.repositories import HostRepository, InstanceRepository
from app.runtimes.base import HostInfo, RuntimeContext
from app.runtimes.factory import RuntimeFactory
from app.security.crypto import get_cipher
from app.services.configuration_service import ConfigurationService
from app.services.notification_service import notify_operators
from app.services.settings_service import get_settings_service
from app.ssh.factory import get_ssh_factory
from app.utils.time import utcnow

log = get_logger(__name__)


class ReconciliationService:
    def __init__(self) -> None:
        self.instances = InstanceRepository()
        self.hosts = HostRepository()
        self.config = ConfigurationService()

    def reconcile_all(self) -> dict[str, Any]:
        summary = {"hosts": 0, "instances": 0, "drift": 0, "errors": 0, "remediated": 0}
        for host in self.hosts.enabled():
            summary["hosts"] += 1
            result = self.reconcile_host(host)
            summary["instances"] += result["instances"]
            summary["drift"] += result["drift"]
            summary["errors"] += result["errors"]
            summary["remediated"] += result["remediated"]
        return summary

    def reconcile_host(self, host) -> dict[str, Any]:
        result = {
            "host": host.name,
            "instances": 0,
            "drift": 0,
            "errors": 0,
            "remediated": 0,
            "details": [],
        }
        instances = [
            i for i in self.instances.for_host(host.id) if i.current_version_id is not None
        ]
        if not instances:
            return result
        settings = get_settings_service()
        remediate = (
            bool(settings.get("SCARLET_RECONCILE_AUTO_REMEDIATE", False)) and not host.is_production
        )
        try:
            client = get_ssh_factory().connect(host)
        except ScarletError as exc:
            host.status = HostStatus.OFFLINE.value
            host.last_error = exc.message
            db.session.commit()
            result["errors"] += 1
            result["details"].append({"error": exc.message})
            if exc.code != "SSH_HOST_KEY_ERROR":
                notify_operators(
                    "HOST_UNREACHABLE",
                    f"Host {host.name} unreachable",
                    exc.message,
                    level=NotificationLevel.WARNING,
                    link=f"/hosts/{host.id}",
                )
            return result
        host.status = HostStatus.ONLINE.value
        host.last_seen_at = utcnow()
        host.last_error = None
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
        try:
            adapter = RuntimeFactory.get(host.runtime_type)
            for instance in instances:
                result["instances"] += 1
                try:
                    outcome = self._reconcile_instance(
                        instance, host, client, info, adapter, remediate
                    )
                    result["details"].append(outcome)
                    if outcome.get("drift"):
                        result["drift"] += 1
                    if outcome.get("remediated"):
                        result["remediated"] += 1
                except ScarletError as exc:
                    result["errors"] += 1
                    result["details"].append(
                        {"application": instance.application.code, "error": exc.message}
                    )
        finally:
            info.kubeconfig = None
            client.close()
            db.session.commit()
        return result

    def _reconcile_instance(
        self, instance, host, client, info, adapter, remediate: bool
    ) -> dict[str, Any]:
        application = instance.application
        version = instance.desired_version or instance.current_version
        env_vars, _ = self.config.render_environment(
            application, host.environment, version.manifest or {}
        )
        desired = build_desired_state(application, version, host, env_vars)
        if instance.desired_state == DesiredState.STOPPED.value:
            desired = DesiredApplicationState(**{**desired.__dict__, "state": DesiredState.STOPPED})
        if get_lock_manager().is_locked(runtime_lock_key(host.id, application.id)):
            return {"application": application.code, "skipped": "operation in progress"}
        ctx = RuntimeContext(
            executor=client,
            host=info,
            application_code=application.code,
            layout=RemoteLayout(info.base_path, application.code),
            timeout=60,
        )
        actual = adapter.status(ctx)
        previous_drift = instance.drift_detected
        drift = compute_drift(desired, actual)
        instance.actual_state = actual.state.value
        instance.actual_version = actual.version or instance.actual_version
        instance.actual_replicas = actual.replicas
        instance.actual_runtime = actual.runtime
        instance.actual_details = actual.details
        instance.actual_observed_at = utcnow()
        if actual.health.value != "UNKNOWN":
            instance.health_status = actual.health.value
        if host.runtime_type != (instance.actual_runtime or host.runtime_type):
            drift.detected = True
            drift.drift_type = DriftType.RUNTIME
        instance.drift_detected = drift.detected
        instance.drift_type = drift.drift_type.value
        instance.drift_details = drift.details if drift.detected else None
        instance.drift_detected_at = (
            utcnow() if drift.detected and not previous_drift else instance.drift_detected_at
        )
        outcome: dict[str, Any] = {
            "application": application.code,
            "drift": drift.detected,
            "drift_type": drift.drift_type.value,
            "actual_state": actual.state.value,
            "actual_version": actual.version,
        }
        if drift.detected and not previous_drift:
            audit.record(
                "DRIFT_DETECTED",
                entity_type="ApplicationInstance",
                entity_id=instance.id,
                application=application,
                target=host,
                result="INFO",
                details=drift.to_dict(),
            )
            notify_operators(
                "DRIFT_DETECTED",
                f"Drift detected: {application.code} on {host.name}",
                f"{drift.drift_type.value}: desired {desired.version}/{desired.state.value}, actual {actual.version}/{actual.state.value}",
                level=NotificationLevel.WARNING,
                link=f"/applications/{application.id}",
            )
        if (
            drift.detected
            and remediate
            and drift.drift_type in {DriftType.UNEXPECTED_STOP, DriftType.STATE}
            and actual.state != ApplicationState.NOT_INSTALLED
        ):
            with get_lock_manager().hold(
                runtime_lock_key(host.id, application.id), ttl=600, description="reconcile"
            ):
                new_actual = adapter.apply(ctx, desired)
            instance.actual_state = new_actual.state.value
            instance.actual_observed_at = utcnow()
            new_drift = compute_drift(desired, new_actual)
            instance.drift_detected = new_drift.detected
            instance.drift_type = new_drift.drift_type.value
            outcome["remediated"] = not new_drift.detected
            audit.record(
                "DRIFT_REMEDIATED",
                entity_type="ApplicationInstance",
                entity_id=instance.id,
                application=application,
                target=host,
                details={"before": drift.to_dict(), "after": new_drift.to_dict()},
            )
        db.session.commit()
        return outcome
