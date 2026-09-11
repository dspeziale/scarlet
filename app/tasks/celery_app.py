"""Celery application bound to the Flask app context.

Tasks run inside ``app.app_context()`` so services, database session and
configuration behave exactly as in a web request. Retries apply only to
errors flagged ``retryable`` (network / SSH / Redis transients), with
exponential backoff. Validation, authorization and command failures are
never retried.
"""

from __future__ import annotations

from celery import Celery, Task
from celery.schedules import schedule

celery = Celery("scarlet")


class FlaskTask(Task):
    """Base task: runs inside the Flask application context, with a DB session per task."""

    abstract = True
    flask_app = None

    def __call__(self, *args, **kwargs):
        from flask import has_app_context

        app = self.flask_app
        if app is None or has_app_context():
            # eager execution inside a request/test context: share the caller's session
            return super().__call__(*args, **kwargs)
        with app.app_context():
            from app.extensions import db

            try:
                return super().__call__(*args, **kwargs)
            finally:
                db.session.remove()


def retry_policy(exc: Exception) -> bool:
    from app.errors import ScarletError

    return isinstance(exc, ScarletError) and bool(exc.retryable)


def init_celery(app) -> Celery:
    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
        task_always_eager=app.config.get("CELERY_TASK_ALWAYS_EAGER", False),
        task_eager_propagates=False,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_time_limit=int(app.config.get("CELERY_TASK_TIME_LIMIT", 3600)),
        task_soft_time_limit=max(60, int(app.config.get("CELERY_TASK_TIME_LIMIT", 3600)) - 60),
        broker_connection_retry_on_startup=True,
        result_expires=7 * 24 * 3600,
        task_default_queue="scarlet",
        task_routes={
            "scarlet.deploy.*": {"queue": "scarlet-deploy"},
            "scarlet.lifecycle.*": {"queue": "scarlet"},
            "scarlet.host.*": {"queue": "scarlet"},
            "scarlet.maintenance.*": {"queue": "scarlet-maintenance"},
        },
        beat_schedule={
            "reconcile-instances": {
                "task": "scarlet.maintenance.reconcile",
                "schedule": schedule(
                    run_every=int(app.config.get("SCARLET_RECONCILE_INTERVAL", 300))
                ),
            },
            "cleanup": {
                "task": "scarlet.maintenance.cleanup",
                "schedule": schedule(run_every=6 * 3600),
            },
            "health-sweep": {
                "task": "scarlet.maintenance.health_sweep",
                "schedule": schedule(run_every=600),
            },
        },
    )
    FlaskTask.flask_app = app
    celery.Task = FlaskTask
    app.extensions["celery"] = celery
    # register task modules

    return celery
