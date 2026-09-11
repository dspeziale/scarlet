"""Deployment orchestration: request validation, PROD safety, approval, queueing, rollback."""

from __future__ import annotations

from typing import Any

from app.audit import audit
from app.config.logging import current_context
from app.deployment.state_machine import DeploymentStateMachine
from app.errors import ConflictError, NotFoundError, ProductionSafetyError, ValidationError
from app.extensions import db
from app.models.application import Application, ApplicationVersion
from app.models.deployment import Deployment, DeploymentApproval, DeploymentBatch
from app.models.enums import (
    ApprovalStatus,
    AuditResult,
    DeploymentKind,
    DeploymentStatus,
    DeploymentStrategy,
)
from app.models.host import TargetHost
from app.repositories import (
    ApplicationRepository,
    DeploymentRepository,
    HostGroupRepository,
    HostRepository,
    InstanceRepository,
    VersionRepository,
)
from app.security.prod_guard import ProductionGuard
from app.services.application_service import ApplicationService
from app.services.preflight_service import PreflightService
from app.services.settings_service import get_settings_service
from app.utils.ids import new_reference
from app.utils.time import utcnow


class DeploymentService:
    def __init__(self) -> None:
        self.deployments = DeploymentRepository()
        self.apps = ApplicationRepository()
        self.versions = VersionRepository()
        self.hosts = HostRepository()
        self.groups = HostGroupRepository()
        self.instances = InstanceRepository()
        self.app_service = ApplicationService()
        self.preflight = PreflightService()
        self.guard = ProductionGuard(get_settings_service())

    # --- lookups ---------------------------------------------------------------------------
    def _resolve(
        self, application_id: int, version_id: int, host_ids: list[int], host_group_id: int | None
    ) -> tuple[Application, ApplicationVersion, list[TargetHost]]:
        application = self.apps.get_or_404(application_id, "Application")
        version = self.versions.get_or_404(version_id, "Version")
        if version.application_id != application.id:
            raise ValidationError("Version does not belong to the selected application.")
        hosts: list[TargetHost] = []
        if host_group_id:
            group = self.groups.get_or_404(host_group_id, "HostGroup")
            hosts.extend(group.hosts)
        for hid in host_ids or []:
            host = self.hosts.get_or_404(int(hid), "Host")
            if host not in hosts:
                hosts.append(host)
        if not hosts:
            raise ValidationError(
                "Select at least one target host.", errors={"host_ids": ["Required."]}
            )
        return application, version, hosts

    # --- pre-flight for the wizard ---------------------------------------------------------------
    def preflight_for(
        self,
        *,
        application_id: int,
        version_id: int,
        host_ids: list[int],
        host_group_id: int | None = None,
        remote: bool = True,
        user=None,
    ) -> dict[str, Any]:
        application, version, hosts = self._resolve(
            application_id, version_id, host_ids, host_group_id
        )
        results = []
        for host in hosts:
            self.guard.authorize("deployment.execute", host.environment, user=user)
            result = self.preflight.run(application, version, host, remote=remote)
            results.append(
                {
                    "host": host.to_dict(include_system=False),
                    "requirements": self.guard.requirements(host.environment).to_dict(),
                    **result.to_dict(),
                }
            )
        return {
            "application": application.to_dict(),
            "version": version.to_dict(),
            "hosts": results,
            "ok": all(r["ok"] for r in results),
        }

    # --- creation ------------------------------------------------------------------------------------
    def create(
        self,
        *,
        application_id: int,
        version_id: int,
        host_ids: list[int],
        host_group_id: int | None = None,
        strategy: str = "SEQUENTIAL",
        reason: str = "",
        confirmation: str | None = None,
        auto_rollback: bool | None = None,
        max_parallel: int | None = None,
        stop_on_failure: bool = True,
        user=None,
        run_preflight: bool = True,
    ) -> DeploymentBatch:
        application, version, hosts = self._resolve(
            application_id, version_id, host_ids, host_group_id
        )
        strat = DeploymentStrategy.parse(strategy)
        if strat is None or strat == DeploymentStrategy.CANARY:
            raise ValidationError(
                "Strategy must be SEQUENTIAL or PARALLEL.",
                errors={"strategy": ["CANARY is not available yet."]},
            )
        reason = (reason or "").strip()[:2000]
        settings = get_settings_service()
        auto_rb = (
            bool(settings.get("SCARLET_AUTO_ROLLBACK", False))
            if auto_rollback is None
            else bool(auto_rollback)
        )

        # authorization + PROD controls per host
        for host in hosts:
            self.guard.authorize("deployment.execute", host.environment, user=user)
            self.guard.check_operation(
                environment=host.environment,
                operation="DEPLOY",
                confirmation=confirmation,
                reason=reason,
            )
            problems = (
                self.app_service.check_target_compatibility(application, version, host)
                if False
                else self.app_service.check_target_compatibility(application, host, version)
            )
            if problems:
                raise ValidationError(
                    f"Target {host.name} is not compatible: {'; '.join(problems)}",
                    errors={"host_ids": problems},
                )
            if self.deployments.active_for(application.id, host.id):
                raise ConflictError(
                    f"A deployment of {application.code} is already in progress on {host.name}."
                )
            if run_preflight:
                pf = self.preflight.run(application, version, host, remote=False)
                if not pf.ok:
                    failed = [f"{c.label}: {c.message}" for c in pf.checks if c.status == "FAIL"]
                    raise ValidationError(
                        f"Pre-flight failed for {host.name}: {'; '.join(failed)}",
                        errors={"preflight": failed},
                    )

        prod_hosts = [h for h in hosts if h.is_production]
        if prod_hosts:
            limit = int(settings.get("SCARLET_PROD_MAX_PARALLEL_DEPLOYMENTS", 1))
            max_parallel = min(max_parallel or limit, limit)
        else:
            limit = int(settings.get("SCARLET_MAX_PARALLEL_DEPLOYMENTS", 3))
            max_parallel = min(max_parallel or limit, limit)
        if strat == DeploymentStrategy.SEQUENTIAL:
            max_parallel = 1

        batch = DeploymentBatch(
            reference="pending",
            application_id=application.id,
            version_id=version.id,
            strategy=strat.value,
            max_parallel=max_parallel,
            stop_on_failure=stop_on_failure,
            requested_by_id=getattr(user, "id", None),
            reason=reason,
        )
        db.session.add(batch)
        db.session.flush()
        batch.reference = new_reference("BATCH", batch.id)
        request_id = current_context().get("request_id")
        needs_approval = False
        for host in hosts:
            instance = self.instances.get_or_create(application.id, host.id)
            deployment = Deployment(
                reference="pending",
                kind=DeploymentKind.DEPLOY.value,
                batch_id=batch.id,
                application_id=application.id,
                version_id=version.id,
                previous_version_id=(
                    instance.current_version_id
                    if instance.current_version_id != version.id
                    else None
                ),
                target_id=host.id,
                environment_id=host.environment_id,
                instance_id=instance.id,
                status=DeploymentStatus.CREATED.value,
                strategy=strat.value,
                requested_by_id=getattr(user, "id", None),
                reason=reason,
                request_id=request_id,
                auto_rollback=auto_rb,
                confirmed=bool(confirmation) or not host.is_production,
            )
            db.session.add(deployment)
            db.session.flush()
            deployment.reference = new_reference("DEP", deployment.id)
            reqs = self.guard.requirements(host.environment)
            sm = DeploymentStateMachine(deployment)
            if reqs.require_approval:
                sm.transition(DeploymentStatus.PENDING_APPROVAL)
                db.session.add(
                    DeploymentApproval(
                        deployment_id=deployment.id,
                        requested_by_id=getattr(user, "id", None),
                        status=ApprovalStatus.PENDING.value,
                    )
                )
                needs_approval = True
            else:
                sm.transition(DeploymentStatus.QUEUED)
                deployment.queued_at = utcnow()
            audit.record(
                "DEPLOYMENT_STARTED" if not reqs.require_approval else "DEPLOYMENT_REQUESTED",
                user=user,
                entity_type="Deployment",
                entity_id=deployment.id,
                application=application,
                target=host,
                details={
                    "reference": deployment.reference,
                    "version": version.version,
                    "strategy": strat.value,
                    "reason": reason,
                    "auto_rollback": auto_rb,
                    "batch": batch.reference,
                },
            )
        db.session.commit()
        if needs_approval:
            from app.services.notification_service import NotificationService

            NotificationService().notify(
                "APPROVAL_REQUESTED",
                f"Approval requested: {application.code} {version.version}",
                f"{getattr(user, 'username', 'someone')} requested a PROD deployment ({batch.reference}). Reason: {reason}",
                level="WARNING",
                permission="deployment.approve",
                link=f"/deployments?batch={batch.id}",
                email=True,
            )
        self._dispatch_batch(batch)
        return batch

    def _dispatch_batch(self, batch: DeploymentBatch) -> None:
        ready = [d for d in batch.deployments if d.status == DeploymentStatus.QUEUED.value]
        if not ready:
            return
        from app.tasks.deployment_tasks import run_deployment_batch

        result = run_deployment_batch.delay(batch.id)
        for d in ready:
            d.job_id = d.job_id or getattr(result, "id", None)
        db.session.commit()

    # --- approval -------------------------------------------------------------------------------------------
    def approve(
        self, deployment: Deployment, *, user, comment: str = "", approve: bool = True
    ) -> Deployment:
        if deployment.status != DeploymentStatus.PENDING_APPROVAL.value:
            raise ConflictError("Deployment is not waiting for approval.")
        if deployment.requested_by_id == getattr(user, "id", None):
            raise ProductionSafetyError(
                "A deployment cannot be approved by the user who requested it."
            )
        approval = next(
            (a for a in deployment.approvals if a.status == ApprovalStatus.PENDING.value), None
        )
        if approval is None:
            approval = DeploymentApproval(
                deployment_id=deployment.id, requested_by_id=deployment.requested_by_id
            )
            db.session.add(approval)
        approval.decided_by_id = user.id
        approval.decided_at = utcnow()
        approval.comment = (comment or "")[:2000]
        sm = DeploymentStateMachine(deployment)
        if approve:
            approval.status = ApprovalStatus.APPROVED.value
            sm.transition(DeploymentStatus.APPROVED)
            sm.transition(DeploymentStatus.QUEUED)
            deployment.queued_at = utcnow()
            action = "DEPLOYMENT_APPROVED"
        else:
            approval.status = ApprovalStatus.REJECTED.value
            sm.transition(DeploymentStatus.REJECTED)
            deployment.completed_at = utcnow()
            action = "DEPLOYMENT_REJECTED"
        db.session.commit()
        audit.record(
            action,
            user=user,
            entity_type="Deployment",
            entity_id=deployment.id,
            application=deployment.application,
            target=deployment.target,
            details={"reference": deployment.reference, "comment": comment},
        )
        if approve and deployment.batch is not None:
            self._dispatch_batch(deployment.batch)
        return deployment

    def cancel(self, deployment: Deployment, *, user=None, reason: str = "") -> Deployment:
        sm = DeploymentStateMachine(deployment)
        if sm.state not in {
            DeploymentStatus.CREATED,
            DeploymentStatus.PENDING_APPROVAL,
            DeploymentStatus.APPROVED,
            DeploymentStatus.QUEUED,
        }:
            raise ConflictError("Only deployments that have not started can be cancelled.")
        sm.transition(DeploymentStatus.CANCELLED)
        deployment.completed_at = utcnow()
        deployment.error_message = (reason or "Cancelled by operator")[:2000]
        db.session.commit()
        audit.record(
            "DEPLOYMENT_CANCELLED",
            user=user,
            entity_type="Deployment",
            entity_id=deployment.id,
            application=deployment.application,
            target=deployment.target,
            details={"reference": deployment.reference, "reason": reason},
        )
        return deployment

    # --- rollback ---------------------------------------------------------------------------------------------------
    def rollback(
        self,
        *,
        application_id: int,
        host_id: int,
        target_version_id: int | None = None,
        reason: str = "",
        confirmation: str | None = None,
        user=None,
    ) -> Deployment:
        application = self.apps.get_or_404(application_id, "Application")
        host = self.hosts.get_or_404(host_id, "Host")
        self.guard.authorize("deployment.rollback", host.environment, user=user)
        self.guard.check_operation(
            environment=host.environment,
            operation="ROLLBACK",
            confirmation=confirmation,
            reason=reason,
        )
        instance = self.instances.get_for(application.id, host.id)
        if instance is None or instance.current_version_id is None:
            raise NotFoundError("Nothing is deployed for this application on this host.")
        if target_version_id is not None:
            target_version = self.versions.get_or_404(target_version_id, "Version")
            if target_version.application_id != application.id:
                raise ValidationError("Version belongs to a different application.")
        elif instance.previous_version_id is not None:
            target_version = instance.previous_version
        else:
            history = [
                d
                for d in self.deployments.history_for_instance(application.id, host.id)
                if d.status == DeploymentStatus.SUCCESS.value
                and d.version_id != instance.current_version_id
            ]
            if not history:
                raise NotFoundError("No previous successful release is available for rollback.")
            target_version = history[0].version
        if target_version.id == instance.current_version_id:
            raise ConflictError(f"Version {target_version.version} is already the current version.")
        if not target_version.is_active:
            raise ValidationError(
                f"Version {target_version.version} is deactivated and cannot be restored."
            )
        if self.deployments.active_for(application.id, host.id):
            raise ConflictError("A deployment is already in progress on this host.")
        last_success = next(
            (
                d
                for d in self.deployments.history_for_instance(application.id, host.id)
                if d.status == DeploymentStatus.SUCCESS.value
            ),
            None,
        )
        deployment = Deployment(
            reference="pending",
            kind=DeploymentKind.ROLLBACK.value,
            application_id=application.id,
            version_id=target_version.id,
            previous_version_id=instance.current_version_id,
            target_id=host.id,
            environment_id=host.environment_id,
            instance_id=instance.id,
            status=DeploymentStatus.CREATED.value,
            strategy=DeploymentStrategy.SEQUENTIAL.value,
            requested_by_id=getattr(user, "id", None),
            reason=(reason or "").strip()[:2000],
            request_id=current_context().get("request_id"),
            rollback_of_id=last_success.id if last_success else None,
            auto_rollback=False,
            confirmed=True,
        )
        db.session.add(deployment)
        db.session.flush()
        deployment.reference = new_reference("RBK", deployment.id)
        DeploymentStateMachine(deployment).transition(DeploymentStatus.QUEUED)
        deployment.queued_at = utcnow()
        db.session.commit()
        audit.record(
            "ROLLBACK_STARTED",
            user=user,
            entity_type="Deployment",
            entity_id=deployment.id,
            application=application,
            target=host,
            details={
                "reference": deployment.reference,
                "from_version": (
                    instance.current_version.version if instance.current_version else None
                ),
                "to_version": target_version.version,
                "reason": reason,
            },
        )
        from app.tasks.deployment_tasks import deploy_application

        result = deploy_application.delay(deployment.id)
        deployment.job_id = getattr(result, "id", None)
        db.session.commit()
        return deployment

    # --- read ---------------------------------------------------------------------------------------------------------------
    def get(self, deployment_id: int) -> Deployment:
        deployment = self.deployments.get(deployment_id)
        if deployment is None:
            raise NotFoundError(f"Deployment {deployment_id} not found.")
        return deployment

    def timeline(self, deployment: Deployment) -> list[dict[str, Any]]:
        events = [
            {
                "time": deployment.created_at.isoformat(),
                "state": "CREATED",
                "label": "Deployment created",
            }
        ]
        if deployment.queued_at:
            events.append(
                {"time": deployment.queued_at.isoformat(), "state": "QUEUED", "label": "Queued"}
            )
        if deployment.started_at:
            events.append(
                {
                    "time": deployment.started_at.isoformat(),
                    "state": "RUNNING",
                    "label": "Execution started",
                }
            )
        for step in deployment.steps:
            if step.started_at:
                events.append(
                    {
                        "time": step.started_at.isoformat(),
                        "state": step.name.upper(),
                        "label": step.label,
                        "status": step.status,
                        "duration_seconds": step.duration_seconds,
                    }
                )
        if deployment.completed_at:
            events.append(
                {
                    "time": deployment.completed_at.isoformat(),
                    "state": deployment.status,
                    "label": f"Finished: {deployment.status}",
                    "duration_seconds": deployment.duration_seconds,
                }
            )
        return events

    def mark_failed_externally(self, deployment: Deployment, message: str) -> None:
        """Used by the worker when a task crashes outside the engine (timeout, lost worker)."""
        sm = DeploymentStateMachine(deployment)
        if not sm.is_terminal:
            sm.fail(code="WORKER_FAILURE", message=message[:2000])
            deployment.completed_at = utcnow()
            db.session.commit()
            audit.record(
                "DEPLOYMENT_FAILED",
                entity_type="Deployment",
                entity_id=deployment.id,
                application=deployment.application,
                target=deployment.target,
                result=AuditResult.FAILURE,
                details={"reference": deployment.reference, "error": message},
            )
