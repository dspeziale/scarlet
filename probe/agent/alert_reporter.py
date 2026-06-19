"""
Tails Suricata's EVE JSON log and batches alert events to the server.

Uses inotify-style file watching (watchdog) with a fallback polling loop.
Events are buffered and flushed every ALERT_FLUSH_INTERVAL seconds or
when the batch reaches MAX_BATCH_SIZE.  On failure the batch is pushed
to the local SQLite queue for later replay.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

import httpx
import structlog

from local_queue import LocalQueue

log = structlog.get_logger(__name__)

MAX_BATCH_SIZE = 200
ALERT_EVENT_TYPE = "alert"


class AlertReporter(threading.Thread):
    def __init__(
        self,
        server_url: str,
        probe_id: str,
        eve_log: Path,
        flush_interval: int,
        http_client: httpx.Client,
        queue: LocalQueue,
    ) -> None:
        super().__init__(name="alert-reporter", daemon=True)
        self._url = f"{server_url}/api/v1/probes/{probe_id}/ids/alerts"
        self._eve_log = eve_log
        self._flush_interval = flush_interval
        self._http = http_client
        self._queue = queue
        self._buffer: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._inode: Optional[int] = None
        self._offset: int = 0

    def run(self) -> None:
        log.info("alert_reporter_started", flush_interval=self._flush_interval)
        # First: drain any queued alerts from prior run
        self._replay_queued()
        last_flush = time.monotonic()
        while not self._stop.is_set():
            self._tail_once()
            elapsed = time.monotonic() - last_flush
            with self._lock:
                should_flush = len(self._buffer) >= MAX_BATCH_SIZE or elapsed >= self._flush_interval
            if should_flush:
                self._flush()
                last_flush = time.monotonic()
            self._stop.wait(1)

    def shutdown(self) -> None:
        self._stop.set()
        self._flush()

    # ── Tail ─────────────────────────────────────────────────────────────

    def _tail_once(self) -> None:
        if not self._eve_log.exists():
            return
        try:
            stat = os.stat(self._eve_log)
        except OSError:
            return

        # Detect log rotation
        if self._inode is not None and stat.st_ino != self._inode:
            log.info("eve_log_rotated")
            self._offset = 0

        self._inode = stat.st_ino

        if stat.st_size < self._offset:
            self._offset = 0

        if stat.st_size == self._offset:
            return

        with open(self._eve_log, "r", errors="replace") as fh:
            fh.seek(self._offset)
            for raw_line in fh:
                self._offset += len(raw_line.encode())
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event_type") == ALERT_EVENT_TYPE:
                    with self._lock:
                        self._buffer.append(event)

    # ── Flush ─────────────────────────────────────────────────────────────

    def _flush(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:MAX_BATCH_SIZE]
            self._buffer = self._buffer[MAX_BATCH_SIZE:]

        try:
            resp = self._http.post(self._url, json={"alerts": batch}, timeout=20)
            resp.raise_for_status()
            log.info("alerts_flushed", count=len(batch))
        except Exception as exc:
            log.warning("alerts_flush_failed", error=str(exc), queuing=len(batch))
            self._queue.push("alerts", {"alerts": batch})

    def _replay_queued(self) -> None:
        items = self._queue.peek("alerts", limit=10)
        if not items:
            return
        log.info("replaying_queued_alerts", batches=len(items))
        for row_id, payload in items:
            try:
                resp = self._http.post(self._url, json=payload, timeout=20)
                resp.raise_for_status()
                self._queue.ack([row_id])
            except Exception as exc:
                log.warning("replay_failed", row_id=row_id, error=str(exc))
                self._queue.increment_retry(row_id)
