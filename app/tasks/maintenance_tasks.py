"""Periodic maintenance: reconciliation, cleanup, health sweep, remote release pruning."""

from __future__ import annotations

from app.config.logging import get_logger
from app.errors import ScarletError
from app.extensions import db
from app.tasks.celery_app import celery

log = get_logger(__name__)


@celery.task(name="scarlet.maintenance.reconcile")
def reconcile() -> dict:
    from app.services.reconciliation_service import ReconciliationService
    from app.services.settings_service import get_settings_service

    if not get_settings_service().get("SCARLET_RECONCILE_ENABLED", True):
        return {"skipped": True}
    summary = ReconciliationService().reconcile_all()
    log.info("reconciliation finished", extra={"extra_data": summary})
    return summary


@celery.task(name="scarlet.maintenance.reconcile_host")
def reconcile_host(host_id: int) -> dict:
    from app.models.host import TargetHost
    from app.services.reconciliation_service import ReconciliationService

    host = db.session.get(TargetHost, host_id)
    if host is None or not host.enabled:
        return {"skipped": True}
    return ReconciliationService().reconcile_host(host)


@celery.task(name="scarlet.maintenance.cleanup")
def cleanup() -> dict:
    from app.services.cleanup_service import CleanupService

    summary = CleanupService().run_all()
    log.info("cleanup finished", extra={"extra_data": summary})
    return summary


@celery.task(name="scarlet.maintenance.cleanup_remote_releases")
def cleanup_remote_releases(host_id: int, application_id: int) -> dict:
    from app.models.application import Application
    from app.models.host import TargetHost
    from app.services.cleanup_service import CleanupService

    host = db.session.get(TargetHost, host_id)
    application = db.session.get(Application, application_id)
    if host is None or application is None:
        return {"skipped": True}
    try:
        return CleanupService().cleanup_remote_releases(host, application)
    except ScarletError as exc:
        return {"error": exc.message}


@celery.task(name="scarlet.maintenance.health_sweep")
def health_sweep() -> dict:
    """Queue a HEALTH operation for every running instance."""
    from app.models.enums import OperationType
    from app.repositories import InstanceRepository
    from app.services.operation_service import OperationService
    from app.tasks.lifecycle_tasks import run_lifecycle_operation

    queued = 0
    ops = OperationService()
    for instance in InstanceRepository().all_active():
        if instance.current_version_id is None or instance.desired_state != "RUNNING":
            continue
        operation = ops.create(
            OperationType.HEALTH,
            application=instance.application,
            target=instance.host,
            instance=instance,
            reason="scheduled health sweep",
            parameters={},
        )
        run_lifecycle_operation.delay(operation.id)
        queued += 1
    return {"queued": queued}
