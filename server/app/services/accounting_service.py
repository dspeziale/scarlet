"""Resource usage accounting service."""

from __future__ import annotations

from datetime import date, datetime, timezone

import structlog
from sqlalchemy import func, select

from app.extensions import db
from app.models.telemetry import UsageAccounting

log = structlog.get_logger(__name__)


class AccountingService:
    def record_usage(self, tenant_id: str, probe_id: str, metrics: dict) -> UsageAccounting:
        today = date.today()

        stmt = select(UsageAccounting).where(
            UsageAccounting.tenant_id == tenant_id,
            UsageAccounting.probe_id == probe_id,
            UsageAccounting.period_date == today,
        )
        record = db.session.execute(stmt).scalar_one_or_none()

        if record is None:
            record = UsageAccounting(
                tenant_id=tenant_id,
                probe_id=probe_id,
                period_date=today,
                cpu_seconds=0, memory_mb=0, network_in_bytes=0,
                network_out_bytes=0, disk_mb=0, task_count=0,
            )
            db.session.add(record)

        # Coalesce in case any column is still NULL (older rows / defaults).
        record.cpu_seconds = (record.cpu_seconds or 0) + float(metrics.get("cpu_seconds", 0))
        record.memory_mb = max(record.memory_mb or 0, float(metrics.get("memory_mb", 0)))
        record.network_in_bytes = (record.network_in_bytes or 0) + int(metrics.get("network_in_bytes", 0))
        record.network_out_bytes = (record.network_out_bytes or 0) + int(metrics.get("network_out_bytes", 0))
        record.disk_mb = max(record.disk_mb or 0, float(metrics.get("disk_mb", 0)))
        record.task_count = (record.task_count or 0) + int(metrics.get("task_count", 0))

        db.session.flush()
        return record

    def get_daily_summary(self, tenant_id: str | None, period_date: date) -> list[dict]:
        stmt = select(UsageAccounting).where(UsageAccounting.period_date == period_date)
        if tenant_id is not None:
            stmt = stmt.where(UsageAccounting.tenant_id == tenant_id)
        rows = db.session.execute(stmt).scalars().all()
        return [r.to_dict() for r in rows]

    def get_monthly_summary(self, tenant_id: str | None, year: int, month: int) -> dict:
        stmt = (
            select(
                func.sum(UsageAccounting.cpu_seconds).label("total_cpu_seconds"),
                func.sum(UsageAccounting.network_in_bytes).label("total_net_in"),
                func.sum(UsageAccounting.network_out_bytes).label("total_net_out"),
                func.sum(UsageAccounting.task_count).label("total_tasks"),
                func.max(UsageAccounting.memory_mb).label("peak_memory_mb"),
                func.max(UsageAccounting.disk_mb).label("peak_disk_mb"),
            )
            .where(
                func.extract("year", UsageAccounting.period_date) == year,
                func.extract("month", UsageAccounting.period_date) == month,
            )
        )
        if tenant_id is not None:
            stmt = stmt.where(UsageAccounting.tenant_id == tenant_id)
        row = db.session.execute(stmt).one()
        return {
            "tenant_id": tenant_id,
            "year": year,
            "month": month,
            "total_cpu_seconds": float(row.total_cpu_seconds or 0),
            "total_net_in_bytes": int(row.total_net_in or 0),
            "total_net_out_bytes": int(row.total_net_out or 0),
            "total_tasks": int(row.total_tasks or 0),
            "peak_memory_mb": float(row.peak_memory_mb or 0),
            "peak_disk_mb": float(row.peak_disk_mb or 0),
        }

    def list_usage(self, tenant_id: str | None, probe_id: str | None = None, limit: int = 30) -> list[UsageAccounting]:
        stmt = select(UsageAccounting)
        if tenant_id is not None:
            stmt = stmt.where(UsageAccounting.tenant_id == tenant_id)
        if probe_id:
            stmt = stmt.where(UsageAccounting.probe_id == probe_id)
        stmt = stmt.order_by(UsageAccounting.period_date.desc()).limit(limit)
        return list(db.session.execute(stmt).scalars())
