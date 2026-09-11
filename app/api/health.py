"""Liveness/readiness endpoints and Prometheus metrics."""

from __future__ import annotations

import time

from flask import Response, current_app, jsonify
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.api import api
from app.extensions import db

registry = CollectorRegistry()
deployments_total = Counter(
    "scarlet_deployments_total",
    "Deployments finished",
    ["result", "environment"],
    registry=registry,
)
operations_total = Counter(
    "scarlet_operations_total",
    "Lifecycle operations finished",
    ["type", "result"],
    registry=registry,
)
operation_duration = Histogram(
    "scarlet_operation_duration_seconds",
    "Operation duration",
    ["type"],
    registry=registry,
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1800),
)
ssh_failures_total = Counter(
    "scarlet_ssh_connection_failures_total", "SSH connection failures", registry=registry
)
hosts_gauge = Gauge("scarlet_hosts", "Hosts by status", ["status"], registry=registry)
instances_gauge = Gauge(
    "scarlet_application_instances", "Instances by state", ["state"], registry=registry
)
drift_gauge = Gauge("scarlet_instances_drift", "Instances with drift detected", registry=registry)
running_deployments_gauge = Gauge(
    "scarlet_deployments_running", "Deployments currently running", registry=registry
)


def _check_database() -> tuple[bool, str]:
    try:
        db.session.execute(db.text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"database error: {type(exc).__name__}"


def _check_redis() -> tuple[bool, str]:
    if current_app.config.get("TESTING") or current_app.config.get("CELERY_TASK_ALWAYS_EAGER"):
        return True, "not required (eager mode)"
    try:
        import redis

        client = redis.Redis.from_url(
            current_app.config["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2
        )
        client.ping()
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"redis error: {type(exc).__name__}"


def _check_workers() -> tuple[bool, str]:
    if current_app.config.get("TESTING") or current_app.config.get("CELERY_TASK_ALWAYS_EAGER"):
        return True, "not required (eager mode)"
    try:
        from app.tasks.celery_app import celery

        replies = celery.control.ping(timeout=1.0)
        count = len(replies or [])
        return count > 0, f"{count} worker(s)"
    except Exception as exc:  # noqa: BLE001
        return False, f"worker check failed: {type(exc).__name__}"


@api.get("/health")
def health():
    """Liveness: the process is up and can reach the database."""
    ok_db, msg = _check_database()
    status = 200 if ok_db else 503
    return (
        jsonify(
            {
                "status": "ok" if ok_db else "degraded",
                "database": msg,
                "version": current_app.config.get("APP_VERSION"),
            }
        ),
        status,
    )


@api.get("/ready")
def ready():
    """Readiness: database, redis and (best effort) workers."""
    checks = {"database": _check_database(), "redis": _check_redis(), "workers": _check_workers()}
    critical_ok = checks["database"][0] and checks["redis"][0]
    return jsonify(
        {
            "status": "ready" if critical_ok else "not-ready",
            "checks": {k: {"ok": v[0], "message": v[1]} for k, v in checks.items()},
        }
    ), (200 if critical_ok else 503)


@api.get("/metrics")
def metrics():
    from sqlalchemy import func

    from app.models import ApplicationInstance, TargetHost
    from app.repositories import DeploymentRepository

    try:
        for status, count in db.session.execute(
            db.select(TargetHost.status, func.count(TargetHost.id)).group_by(TargetHost.status)
        ).all():
            hosts_gauge.labels(status=status).set(count)
        for state, count in db.session.execute(
            db.select(
                ApplicationInstance.actual_state, func.count(ApplicationInstance.id)
            ).group_by(ApplicationInstance.actual_state)
        ).all():
            instances_gauge.labels(state=state).set(count)
        drift_gauge.set(
            db.session.execute(
                db.select(func.count(ApplicationInstance.id)).where(
                    ApplicationInstance.drift_detected.is_(True)
                )
            ).scalar_one()
        )
        running_deployments_gauge.set(DeploymentRepository().running_count())
    except Exception:  # noqa: BLE001 - metrics must never fail hard
        pass
    return Response(generate_latest(registry), mimetype=CONTENT_TYPE_LATEST)


def observe_operation(op_type: str, result: str, started: float | None) -> None:
    operations_total.labels(type=op_type, result=result).inc()
    if started is not None:
        operation_duration.labels(type=op_type).observe(max(0.0, time.monotonic() - started))
