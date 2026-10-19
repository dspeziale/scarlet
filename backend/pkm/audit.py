"""Audit log of significant administrative operations."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from .db import Database, iso, utcnow

log = logging.getLogger("pkm.audit")

# Keys whose values must never reach the audit log.
_SENSITIVE = {"password", "new_password", "current_password", "token", "data", "stringData", "secret"}


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("<redacted>" if k in _SENSITIVE else _scrub(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


@dataclass
class AuditContext:
    user_id: int | None
    username: str
    ip: str = ""
    user_agent: str = ""
    session_ref: str = ""
    request_id: str = ""


class AuditService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        ctx: AuditContext,
        action: str,
        *,
        result: str = "success",
        kind: str = "",
        name: str = "",
        namespace: str = "",
        detail: dict[str, Any] | None = None,
    ) -> None:
        payload = json.dumps(_scrub(detail or {}), ensure_ascii=False, default=str)[:20000]
        try:
            with self.db.connect() as c:
                c.execute(
                    "INSERT INTO audit_log(ts, user_id, username, action, resource_kind, resource_name, "
                    "namespace, result, detail, ip, user_agent, session_ref, request_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (iso(), ctx.user_id, ctx.username, action, kind, name, namespace, result, payload,
                     ctx.ip[:64], ctx.user_agent[:300], ctx.session_ref, ctx.request_id),
                )  # fmt: skip
        except Exception:  # the audit failure must be visible in the service log
            log.exception("failed to write audit record", extra={"action": action})
            raise
        log.info(
            "audit",
            extra={"audit_action": action, "user": ctx.username, "result": result, "kind": kind,
                   "resource": name, "namespace": namespace},
        )  # fmt: skip

    def search(
        self,
        *,
        q: str | None = None,
        username: str | None = None,
        action: str | None = None,
        result: str | None = None,
        namespace: str | None = None,
        kind: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        where: list[str] = []
        args: list[Any] = []
        if q:
            where.append(
                "(username LIKE ? OR action LIKE ? OR resource_name LIKE ? OR namespace LIKE ? OR detail LIKE ?)"
            )
            like = f"%{q}%"
            args += [like] * 5
        for col, val in (("username", username), ("result", result), ("namespace", namespace),
                         ("resource_kind", kind)):  # fmt: skip
            if val:
                where.append(f"{col} = ?")
                args.append(val)
        if action:
            where.append("action LIKE ?")
            args.append(f"{action}%")
        if since:
            where.append("ts >= ?")
            args.append(since)
        if until:
            where.append("ts <= ?")
            args.append(until)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        limit = max(1, min(limit, 500))
        with self.db.connect() as c:
            total = c.execute(f"SELECT COUNT(*) FROM audit_log {clause}", args).fetchone()[0]  # noqa: S608
            rows = c.execute(
                f"SELECT * FROM audit_log {clause} ORDER BY id DESC LIMIT ? OFFSET ?",  # noqa: S608
                [*args, limit, max(0, offset)],
            ).fetchall()
        items = []
        for r in rows:
            d = dict(r)
            try:
                d["detail"] = json.loads(d["detail"])
            except ValueError:
                pass
            items.append(d)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def get(self, entry_id: int) -> dict[str, Any] | None:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM audit_log WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["detail"] = json.loads(d["detail"] or "{}")
        return d

    def distinct_actions(self) -> list[str]:
        with self.db.connect() as c:
            return [r[0] for r in c.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")]

    def purge(self, retention_days: int) -> int:
        cutoff = iso(utcnow() - timedelta(days=retention_days))
        with self.db.connect() as c:
            return c.execute("DELETE FROM audit_log WHERE ts < ?", (cutoff,)).rowcount
