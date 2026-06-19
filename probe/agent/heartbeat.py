"""
Sends periodic heartbeat to the server with system metrics and IDS status.
Also polls for tasks and executes them synchronously on the heartbeat thread.
"""

from __future__ import annotations

import platform
import resource
import threading
import time
from typing import Callable, Optional

import httpx
import structlog

log = structlog.get_logger(__name__)


class HeartbeatWorker(threading.Thread):
    def __init__(
        self,
        server_url: str,
        probe_id: str,
        interval: int,
        http_client: httpx.Client,
        get_ids_status: Callable[[], dict],
        task_handler: Callable[[dict], None],
    ) -> None:
        super().__init__(name="heartbeat", daemon=True)
        self._hb_url = f"{server_url}/api/v1/probes/{probe_id}/heartbeat"
        self._task_url = f"{server_url}/api/v1/probes/{probe_id}/tasks/pending"
        self._result_url = f"{server_url}/api/v1/probes/{probe_id}/tasks"
        self._interval = interval
        self._http = http_client
        self._get_ids_status = get_ids_status
        self._task_handler = task_handler
        self._stop = threading.Event()

    def run(self) -> None:
        log.info("heartbeat_started", interval=self._interval)
        while not self._stop.is_set():
            try:
                self._beat()
                self._poll_tasks()
            except Exception:
                log.exception("heartbeat_error")
            self._stop.wait(self._interval)

    def shutdown(self) -> None:
        self._stop.set()

    def _beat(self) -> None:
        payload = {
            "status": "online",
            "ids_status": self._get_ids_status(),
            "system": _system_metrics(),
        }
        resp = self._http.post(self._hb_url, json=payload, timeout=10)
        if resp.status_code not in (200, 204):
            log.warning("heartbeat_non_ok", status=resp.status_code)
        else:
            log.debug("heartbeat_sent")

    def _poll_tasks(self) -> None:
        resp = self._http.get(self._task_url, timeout=10)
        if resp.status_code == 200:
            tasks = resp.json().get("tasks", [])
            for task in tasks:
                try:
                    self._task_handler(task)
                except Exception as exc:
                    log.error("task_handler_error", task_id=task.get("id"), error=str(exc))


def _system_metrics() -> dict:
    try:
        import psutil  # optional dependency
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "cpu_pct": cpu,
            "mem_total_mb": mem.total // 1024 // 1024,
            "mem_used_mb": mem.used // 1024 // 1024,
            "disk_total_gb": disk.total // 1024 // 1024 // 1024,
            "disk_free_gb": disk.free // 1024 // 1024 // 1024,
            "platform": platform.system(),
        }
    except ImportError:
        # psutil not installed — return minimal info
        return {"platform": platform.system()}
    except Exception:
        return {}
