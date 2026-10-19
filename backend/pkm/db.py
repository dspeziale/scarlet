"""SQLite storage for application state (users, sessions, audit, settings, notifications, backups).

Kubernetes state is never copied here: it stays in Kubernetes.
A new connection is opened per unit of work; WAL mode allows the web process and
the `pkm-admin` CLI (e.g. the backup timer) to use the database concurrently.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("pkm.db")

MIGRATIONS: list[str] = [
    # 1 - initial schema
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'operator', 'viewer')),
        active INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        language TEXT NOT NULL DEFAULT 'it',
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TEXT,
        last_login_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        csrf_token TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        ip TEXT NOT NULL DEFAULT '',
        user_agent TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_sessions_user ON sessions(user_id);
    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        user_id INTEGER,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        resource_kind TEXT NOT NULL DEFAULT '',
        resource_name TEXT NOT NULL DEFAULT '',
        namespace TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL CHECK (result IN ('success', 'failure', 'denied')),
        detail TEXT NOT NULL DEFAULT '{}',
        ip TEXT NOT NULL DEFAULT '',
        user_agent TEXT NOT NULL DEFAULT '',
        session_ref TEXT NOT NULL DEFAULT '',
        request_id TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_audit_ts ON audit_log(ts);
    CREATE INDEX idx_audit_user ON audit_log(username);
    CREATE INDEX idx_audit_action ON audit_log(action);
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE app_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL UNIQUE,
        severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
        reason TEXT NOT NULL,
        source TEXT NOT NULL,
        resource_kind TEXT NOT NULL DEFAULT '',
        resource_name TEXT NOT NULL DEFAULT '',
        namespace TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        data TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL CHECK (status IN ('open', 'acknowledged', 'resolved')),
        occurrences INTEGER NOT NULL DEFAULT 1,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        acknowledged_by TEXT,
        acknowledged_at TEXT,
        resolved_at TEXT
    );
    CREATE INDEX idx_notifications_status ON notifications(status);
    CREATE TABLE backups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        sha256 TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'deleted')),
        trigger TEXT NOT NULL,
        created_by TEXT NOT NULL DEFAULT '',
        includes TEXT NOT NULL DEFAULT '[]',
        verified_at TEXT,
        verify_result TEXT,
        detail TEXT NOT NULL DEFAULT ''
    );
    """,
]


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self._init_lock = threading.Lock()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = self._open()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._open()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    def migrate(self) -> int:
        with self._init_lock, self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for idx, script in enumerate(MIGRATIONS[current:], start=current + 1):
                log.info("applying database migration", extra={"version": idx})
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in _split_sql(script):
                        conn.execute(stmt)
                    conn.execute("INSERT INTO schema_version(version) VALUES (?)", (idx,))
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
            return len(MIGRATIONS)

    def schema_version(self) -> int:
        with self.connect() as conn:
            row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            return int(row["v"] or 0)

    def ping(self) -> None:
        with self.connect() as conn:
            conn.execute("SELECT 1").fetchone()

    # --- app_state helpers -------------------------------------------------
    def get_state(self, key: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_state(self, key: str, value: str | None) -> None:
        with self.connect() as conn:
            if value is None:
                conn.execute("DELETE FROM app_state WHERE key = ?", (key,))
            else:
                conn.execute(
                    "INSERT INTO app_state(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )

    def backup_to(self, target: str) -> None:
        """Consistent online copy using the SQLite backup API."""
        with self.connect() as src:
            dst = sqlite3.connect(target)
            try:
                src.backup(dst)
            finally:
                dst.close()


def _split_sql(script: str) -> list[str]:
    return [s.strip() for s in script.split(";") if s.strip()]
