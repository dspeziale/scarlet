"""Audit log querying and export (CSV / JSON)."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from typing import Any

from app.audit import audit
from app.repositories import AuditRepository, SecurityEventRepository
from app.repositories.base import Page

EXPORT_COLUMNS = [
    "id",
    "timestamp",
    "username",
    "action",
    "entity_type",
    "entity_id",
    "target_name",
    "application_code",
    "environment",
    "result",
    "ip_address",
    "request_id",
    "details",
]
MAX_EXPORT_ROWS = 100_000


class AuditService:
    def __init__(self) -> None:
        self.repo = AuditRepository()
        self.security_events = SecurityEventRepository()

    def list(self, **params: Any) -> Page:
        return self.repo.list(**params)

    def _rows(self, filters: dict[str, Any]) -> Iterator[dict[str, Any]]:
        count = 0
        for entry in self.repo.iter_filtered(**filters):
            count += 1
            if count > MAX_EXPORT_ROWS:
                break
            yield entry.to_dict()

    def export_csv(self, filters: dict[str, Any], *, user=None) -> str:
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer, fieldnames=EXPORT_COLUMNS, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        rows = 0
        for row in self._rows(filters):
            row["details"] = json.dumps(row.get("details") or {}, default=str)
            # defuse spreadsheet formula injection
            for key, value in row.items():
                if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
                    row[key] = "'" + value
            writer.writerow(row)
            rows += 1
        audit.record(
            "AUDIT_EXPORTED",
            user=user,
            entity_type="AuditLog",
            details={"format": "csv", "rows": rows, "filters": filters},
        )
        return buffer.getvalue()

    def export_json(self, filters: dict[str, Any], *, user=None) -> str:
        rows = list(self._rows(filters))
        audit.record(
            "AUDIT_EXPORTED",
            user=user,
            entity_type="AuditLog",
            details={"format": "json", "rows": len(rows), "filters": filters},
        )
        return json.dumps(
            {"exported": len(rows), "filters": filters, "records": rows}, indent=2, default=str
        )

    def actions(self) -> list[str]:
        from sqlalchemy import distinct

        from app.extensions import db
        from app.models.audit import AuditLog

        return sorted(a for (a,) in db.session.execute(db.select(distinct(AuditLog.action))).all())

    def acknowledge_event(self, event_id: int, *, user=None) -> None:
        from app.extensions import db
        from app.utils.time import utcnow

        event = self.security_events.get_or_404(event_id, "SecurityEvent")
        event.acknowledged = True
        event.acknowledged_by_id = getattr(user, "id", None)
        event.acknowledged_at = utcnow()
        db.session.commit()
        audit.record(
            "SECURITY_EVENT_ACKNOWLEDGED",
            user=user,
            entity_type="SecurityEvent",
            entity_id=event.id,
            details={"event_type": event.event_type},
        )
