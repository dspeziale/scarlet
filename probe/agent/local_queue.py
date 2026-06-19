"""
Persistent local queue backed by SQLite.

When the server is unreachable, outbound payloads (alerts, telemetry, results)
are stored here and replayed on reconnection.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS queue (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    queue     TEXT    NOT NULL,          -- 'alerts' | 'telemetry' | 'results' | 'pcap_meta'
    payload   TEXT    NOT NULL,          -- JSON-encoded payload
    retries   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT   NOT NULL,
    last_try  TEXT
);
"""


class LocalQueue:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute(_CREATE_SQL)
        self._conn.commit()

    def push(self, queue: str, payload: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO queue (queue, payload, created_at) VALUES (?,?,?)",
                (queue, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
            )
            self._conn.commit()
            log.debug("queue_push", queue=queue, rowid=cur.lastrowid)
            return cur.lastrowid

    def peek(self, queue: str, limit: int = 50) -> list[tuple[int, dict]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, payload FROM queue WHERE queue=? ORDER BY id LIMIT ?",
                (queue, limit),
            ).fetchall()
        return [(r[0], json.loads(r[1])) for r in rows]

    def ack(self, row_ids: list[int]) -> None:
        if not row_ids:
            return
        with self._lock:
            placeholders = ",".join("?" * len(row_ids))
            self._conn.execute(f"DELETE FROM queue WHERE id IN ({placeholders})", row_ids)
            self._conn.commit()
        log.debug("queue_ack", count=len(row_ids))

    def increment_retry(self, row_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE queue SET retries=retries+1, last_try=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), row_id),
            )
            self._conn.commit()

    def purge_stale(self, queue: str, max_retries: int = 10) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM queue WHERE queue=? AND retries >= ?",
                (queue, max_retries),
            )
            self._conn.commit()
        removed = cur.rowcount
        if removed:
            log.warning("queue_purge", queue=queue, removed=removed)
        return removed

    def count(self, queue: str | None = None) -> int:
        with self._lock:
            if queue:
                return self._conn.execute(
                    "SELECT COUNT(*) FROM queue WHERE queue=?", (queue,)
                ).fetchone()[0]
            return self._conn.execute("SELECT COUNT(*) FROM queue").fetchone()[0]

    def queues(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT DISTINCT queue FROM queue").fetchall()
        return [r[0] for r in rows]
