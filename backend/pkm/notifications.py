"""Notification Center: problems detected by the monitor, persisted with their lifecycle.

open -> acknowledged ("segna come gestito") -> resolved (automatically when the problem
disappears). A resolved problem that comes back is reopened.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from .db import Database, iso, utcnow
from .errors import NotFound


class NotificationService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def sync(self, source: str, items: list[dict[str, Any]]) -> dict[str, int]:
        """Upsert the current set of problems for a source; resolve the ones not present anymore.

        items: {fingerprint, severity, reason, kind, name, namespace, message, data}
        """
        now = iso()
        seen = set()
        stats = {"new": 0, "reopened": 0, "resolved": 0}
        with self.db.transaction() as c:
            for it in items:
                fp = it["fingerprint"]
                seen.add(fp)
                row = c.execute("SELECT id, status FROM notifications WHERE fingerprint = ?", (fp,)).fetchone()
                data = json.dumps(it.get("data") or {}, default=str)[:20000]
                if row is None:
                    c.execute(
                        "INSERT INTO notifications(fingerprint, severity, reason, source, resource_kind, resource_name, "
                        "namespace, message, data, status, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (fp, it["severity"], it["reason"], source, it.get("kind", ""), it.get("name", ""),
                         it.get("namespace") or "", (it.get("message") or "")[:2000], data, "open", now, now),
                    )  # fmt: skip
                    stats["new"] += 1
                else:
                    reopened = row["status"] == "resolved"
                    c.execute(
                        "UPDATE notifications SET severity=?, message=?, data=?, last_seen=?, "
                        "occurrences = occurrences + 1, resource_name=?, "
                        "status = CASE WHEN status='resolved' THEN 'open' ELSE status END, "
                        "resolved_at = CASE WHEN status='resolved' THEN NULL ELSE resolved_at END, "
                        "first_seen = CASE WHEN status='resolved' THEN ? ELSE first_seen END "
                        "WHERE id = ?",
                        (it["severity"], (it.get("message") or "")[:2000], data, now, it.get("name", ""), now, row["id"]),
                    )  # fmt: skip
                    stats["reopened"] += int(reopened)
            rows = c.execute("SELECT id, fingerprint FROM notifications WHERE source = ? AND status != 'resolved'",
                             (source,)).fetchall()  # fmt: skip
            for r in rows:
                if r["fingerprint"] not in seen:
                    c.execute("UPDATE notifications SET status='resolved', resolved_at=? WHERE id=?", (now, r["id"]))
                    stats["resolved"] += 1
        return stats

    def list(self, *, status: str | None = None, severity: str | None = None, q: str | None = None,
             limit: int = 100, offset: int = 0) -> dict[str, Any]:  # fmt: skip
        where, args = [], []
        if status == "active":
            where.append("status != 'resolved'")
        elif status:
            where.append("status = ?")
            args.append(status)
        if severity:
            where.append("severity = ?")
            args.append(severity)
        if q:
            where.append("(resource_name LIKE ? OR namespace LIKE ? OR reason LIKE ? OR message LIKE ?)")
            args += [f"%{q}%"] * 4
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        order = ("CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'ERROR' THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END, "
                 "last_seen DESC")  # fmt: skip
        with self.db.connect() as c:
            total = c.execute(f"SELECT COUNT(*) FROM notifications {clause}", args).fetchone()[0]  # noqa: S608
            rows = c.execute(f"SELECT * FROM notifications {clause} ORDER BY {order} LIMIT ? OFFSET ?",  # noqa: S608
                             [*args, max(1, min(limit, 500)), max(0, offset)]).fetchall()  # fmt: skip
        items = []
        for r in rows:
            d = dict(r)
            d["data"] = json.loads(d["data"] or "{}")
            items.append(d)
        return {"items": items, "total": total}

    def counts(self) -> dict[str, Any]:
        with self.db.connect() as c:
            rows = c.execute("SELECT severity, status, COUNT(*) AS n FROM notifications WHERE status != 'resolved' "
                             "GROUP BY severity, status").fetchall()  # fmt: skip
        out: dict[str, Any] = {"open": 0, "acknowledged": 0, "bySeverity": {"CRITICAL": 0, "ERROR": 0, "WARNING": 0, "INFO": 0}}
        for r in rows:
            out[r["status"]] += r["n"]
            if r["status"] == "open":
                out["bySeverity"][r["severity"]] += r["n"]
        return out

    def set_ack(self, nid: int, user: str, ack: bool) -> dict[str, Any]:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM notifications WHERE id = ?", (nid,)).fetchone()
            if not row:
                raise NotFound("notification not found")
            if ack and row["status"] == "open":
                c.execute("UPDATE notifications SET status='acknowledged', acknowledged_by=?, acknowledged_at=? "
                          "WHERE id=?", (user, iso(), nid))  # fmt: skip
            elif not ack and row["status"] == "acknowledged":
                c.execute("UPDATE notifications SET status='open', acknowledged_by=NULL, acknowledged_at=NULL "
                          "WHERE id=?", (nid,))  # fmt: skip
            row = c.execute("SELECT * FROM notifications WHERE id = ?", (nid,)).fetchone()
        d = dict(row)
        d["data"] = json.loads(d["data"] or "{}")
        return d

    def purge_resolved(self, older_than_days: int = 30) -> int:
        cutoff = iso(utcnow() - timedelta(days=older_than_days))
        with self.db.connect() as c:
            return c.execute("DELETE FROM notifications WHERE status='resolved' AND resolved_at < ?", (cutoff,)).rowcount
