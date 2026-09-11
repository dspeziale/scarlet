"""Dashboard aggregates."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models import Application, ApplicationInstance, TargetHost
from app.models.enums import ApplicationState, HealthStatus, HostStatus
from app.repositories import (
    AuditRepository,
    DeploymentRepository,
    HostRepository,
    InstanceRepository,
    OperationRepository,
    SecurityEventRepository,
)
from app.utils.time import utcnow


class DashboardService:
    def __init__(self) -> None:
        self.hosts = HostRepository()
        self.deployments = DeploymentRepository()
        self.operations = OperationRepository()
        self.instances = InstanceRepository()
        self.audit = AuditRepository()
        self.security = SecurityEventRepository()

    def summary(self) -> dict[str, Any]:
        env_counts = self.hosts.counts_by_environment()
        total_hosts = db.session.execute(db.select(func.count(TargetHost.id))).scalar_one()
        problem_hosts = list(
            db.session.execute(
                self.hosts.base_query().where(
                    TargetHost.enabled.is_(True), TargetHost.status.in_([HostStatus.OFFLINE.value])
                )
            )
            .scalars()
            .unique()
        )
        pending_keys = list(
            db.session.execute(
                self.hosts.base_query().where(
                    TargetHost.ssh_host_key_status.in_(["PENDING_APPROVAL", "MISMATCH"])
                )
            )
            .scalars()
            .unique()
        )
        state_counts = self.instances.counts_by_state()
        today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        deploy_stats = self.deployments.stats_since(today)
        week_stats = self.deployments.stats_since(utcnow() - timedelta(days=7))
        unhealthy = list(
            db.session.execute(
                self.instances.base_query().where(
                    ApplicationInstance.health_status == HealthStatus.UNHEALTHY.value
                )
            )
            .scalars()
            .unique()
        )
        drifted = list(
            db.session.execute(
                self.instances.base_query().where(ApplicationInstance.drift_detected.is_(True))
            )
            .scalars()
            .unique()
        )
        return {
            "hosts": {
                "total": total_hosts,
                "by_environment": env_counts,
                "dev": env_counts.get("DEV", 0),
                "prod": env_counts.get("PROD", 0),
                "problems": [h.to_dict(include_system=False) for h in problem_hosts],
                "pending_host_keys": [h.to_dict(include_system=False) for h in pending_keys],
            },
            "applications": {
                "total": db.session.execute(db.select(func.count(Application.id))).scalar_one(),
                "running": state_counts.get(ApplicationState.RUNNING.value, 0),
                "stopped": state_counts.get(ApplicationState.STOPPED.value, 0),
                "failed": state_counts.get(ApplicationState.FAILED.value, 0),
                "unknown": state_counts.get(ApplicationState.UNKNOWN.value, 0),
                "by_state": state_counts,
            },
            "deployments": {
                "today": deploy_stats,
                "week": week_stats,
                "running": self.deployments.running_count(),
            },
            "health": {
                "unhealthy": [i.to_dict() for i in unhealthy],
                "drift": [i.to_dict() for i in drifted],
            },
            "recent_deployments": [d.to_dict() for d in self.deployments.recent(8)],
            "recent_operations": [o.to_dict() for o in self.operations.recent(8)],
            "recent_audit": [a.to_dict() for a in self.audit.recent(10)],
            "security_events": [e.to_dict() for e in self.security.unacknowledged(5)],
            "generated_at": utcnow().isoformat(),
        }

    def deployment_trend(self, days: int = 14) -> list[dict[str, Any]]:
        from app.models.deployment import Deployment
        from app.models.enums import FAILED_DEPLOYMENT_STATES, DeploymentStatus

        start = (utcnow() - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        rows = db.session.execute(
            db.select(Deployment.created_at, Deployment.status).where(
                Deployment.created_at >= start
            )
        ).all()
        buckets: dict[str, dict[str, int]] = {}
        for i in range(days):
            day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            buckets[day] = {"date": day, "success": 0, "failed": 0, "other": 0}
        failed = {s.value for s in FAILED_DEPLOYMENT_STATES}
        for created, status in rows:
            key = created.strftime("%Y-%m-%d")
            bucket = buckets.get(key)
            if bucket is None:
                continue
            if status == DeploymentStatus.SUCCESS.value:
                bucket["success"] += 1
            elif status in failed:
                bucket["failed"] += 1
            else:
                bucket["other"] += 1
        return list(buckets.values())
