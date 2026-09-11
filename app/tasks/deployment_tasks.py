"""Deployment jobs."""

from __future__ import annotations

import time

from celery.exceptions import SoftTimeLimitExceeded

from app.config.logging import get_logger
from app.errors import ScarletError
from app.extensions import db
from app.models.deployment import Deployment, DeploymentBatch
from app.models.enums import DeploymentStatus
from app.tasks.celery_app import celery, retry_policy

log = get_logger(__name__)


@celery.task(bind=True, name="scarlet.deploy.deploy_application", max_retries=3)
def deploy_application(self, deployment_id: int) -> dict:
    """Execute one deployment (also used for rollbacks, which are deployments of kind ROLLBACK)."""
    from app.deployment.engine import DeploymentEngine
    from app.services.deployment_service import DeploymentService

    deployment = db.session.get(Deployment, deployment_id)
    if deployment is None:
        return {"ok": False, "error": "deployment not found"}
    if deployment.is_terminal:
        return {"ok": True, "status": deployment.status, "skipped": True}
    try:
        execution = DeploymentEngine().execute(deployment_id, job_id=self.request.id)
        return {
            "ok": execution.status == "SUCCESS",
            "status": deployment.status,
            "reference": deployment.reference,
        }
    except SoftTimeLimitExceeded:
        db.session.rollback()
        deployment = db.session.get(Deployment, deployment_id)
        DeploymentService().mark_failed_externally(deployment, "Worker time limit exceeded.")
        return {"ok": False, "status": deployment.status, "error": "time limit"}
    except ScarletError as exc:
        db.session.rollback()
        deployment = db.session.get(Deployment, deployment_id)
        if (
            retry_policy(exc)
            and deployment is not None
            and deployment.status
            in {
                DeploymentStatus.QUEUED.value,
                DeploymentStatus.VALIDATING.value,
                DeploymentStatus.PREFLIGHT.value,
                DeploymentStatus.TRANSFER_FAILED.value,
                DeploymentStatus.PREFLIGHT_FAILED.value,
            }
            and self.request.retries < self.max_retries
        ):
            # transient error before anything was changed on the host: requeue
            deployment.status = DeploymentStatus.QUEUED.value
            deployment.error_message = f"Transient error, retrying ({self.request.retries + 1}/{self.max_retries}): {exc.message}"
            db.session.commit()
            raise self.retry(exc=exc, countdown=min(300, 15 * (2**self.request.retries))) from exc
        return {
            "ok": False,
            "status": deployment.status if deployment else "UNKNOWN",
            "error": exc.message,
            "code": exc.code,
        }
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log.exception("deployment task crashed")
        deployment = db.session.get(Deployment, deployment_id)
        if deployment is not None:
            DeploymentService().mark_failed_externally(
                deployment, f"Internal error: {type(exc).__name__}"
            )
        return {"ok": False, "error": "internal error"}


@celery.task(bind=True, name="scarlet.deploy.run_deployment_batch")
def run_deployment_batch(self, batch_id: int) -> dict:
    """Run all queued deployments of a batch according to its strategy."""
    batch = db.session.get(DeploymentBatch, batch_id)
    if batch is None:
        return {"ok": False, "error": "batch not found"}
    results: dict[int, str] = {}
    queued = [
        d
        for d in sorted(batch.deployments, key=lambda d: d.id)
        if d.status == DeploymentStatus.QUEUED.value
    ]
    if batch.strategy == "PARALLEL":
        pending = list(queued)
        active: list = []
        while pending or active:
            while pending and len(active) < max(1, batch.max_parallel):
                dep = pending.pop(0)
                active.append((dep.id, deploy_application.apply_async(args=[dep.id])))
            still_active = []
            for dep_id, async_result in active:
                if async_result.ready():
                    db.session.expire_all()
                    dep = db.session.get(Deployment, dep_id)
                    results[dep_id] = dep.status if dep else "UNKNOWN"
                    if batch.stop_on_failure and dep is not None and dep.status_enum.is_failure:
                        for remaining in pending:
                            _cancel(remaining, "Cancelled: another host in the batch failed")
                            results[remaining.id] = DeploymentStatus.CANCELLED.value
                        pending = []
                else:
                    still_active.append((dep_id, async_result))
            active = still_active
            if active:
                time.sleep(2)
        return {
            "ok": all(s == DeploymentStatus.SUCCESS.value for s in results.values()),
            "results": results,
        }
    # SEQUENTIAL
    for index, dep in enumerate(queued):
        db.session.expire_all()
        dep = db.session.get(Deployment, dep.id)
        if dep is None or dep.status != DeploymentStatus.QUEUED.value:
            continue
        deploy_application.apply(args=[dep.id])  # run in-process, in order
        db.session.expire_all()
        dep = db.session.get(Deployment, dep.id)
        results[dep.id] = dep.status
        if batch.stop_on_failure and dep.status_enum.is_failure:
            for remaining in queued[index + 1 :]:
                remaining = db.session.get(Deployment, remaining.id)
                if remaining is not None and remaining.status == DeploymentStatus.QUEUED.value:
                    _cancel(remaining, "Cancelled: previous host in the batch failed")
                    results[remaining.id] = DeploymentStatus.CANCELLED.value
            break
    return {
        "ok": all(s == DeploymentStatus.SUCCESS.value for s in results.values()),
        "results": results,
    }


def _cancel(deployment: Deployment, reason: str) -> None:
    from app.deployment.state_machine import DeploymentStateMachine
    from app.utils.time import utcnow

    sm = DeploymentStateMachine(deployment)
    if sm.state == DeploymentStatus.QUEUED:
        sm.transition(DeploymentStatus.CANCELLED)
        deployment.error_message = reason
        deployment.completed_at = utcnow()
        db.session.commit()
