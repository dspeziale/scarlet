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
        get_network: Optional[Callable[[], dict]] = None,
    ) -> None:
        super().__init__(name="heartbeat", daemon=True)
        self._hb_url = f"{server_url}/api/v1/probes/{probe_id}/heartbeat"
        self._task_url = f"{server_url}/api/v1/probes/{probe_id}/tasks/pending"
        self._result_url = f"{server_url}/api/v1/probes/{probe_id}/tasks"
        self._interval = interval
        self._http = http_client
        self._get_ids_status = get_ids_status
        self._task_handler = task_handler
        self._get_network = get_network
        self._stop = threading.Event()
        # Tasks run in their own threads so a long scan never blocks heartbeats.
        self._inflight: set = set()
        self._inflight_lock = threading.Lock()
        self._last_net: tuple[int, int] | None = None  # (bytes_recv, bytes_sent)

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
        system = _system_metrics()
        system.update(self._net_delta())
        payload = {
            "status": "online",
            "ids_status": self._get_ids_status(),
            "system": system,
        }
        if self._get_network is not None:
            payload["network"] = self._get_network()
        resp = self._http.post(self._hb_url, json=payload, timeout=10)
        if resp.status_code not in (200, 204):
            log.warning("heartbeat_non_ok", status=resp.status_code)
        else:
            log.debug("heartbeat_sent")

    def _net_delta(self) -> dict:
        """Bytes received/sent since the previous heartbeat (cumulative diff)."""
        try:
            import psutil
            io = psutil.net_io_counters()
            cur = (io.bytes_recv, io.bytes_sent)
        except Exception:
            return {}
        prev = self._last_net
        self._last_net = cur
        if prev is None:
            return {"net_in_bytes": 0, "net_out_bytes": 0}
        return {
            "net_in_bytes": max(0, cur[0] - prev[0]),
            "net_out_bytes": max(0, cur[1] - prev[1]),
        }

    def _poll_tasks(self) -> None:
        resp = self._http.get(self._task_url, timeout=10)
        if resp.status_code != 200:
            return
        tasks = resp.json().get("tasks", [])
        for task in tasks:
            task_id = task.get("id")
            # Skip tasks already running — the server keeps listing them as
            # pending until we submit a result, so without this they'd re-run.
            with self._inflight_lock:
                if task_id in self._inflight:
                    continue
                self._inflight.add(task_id)
            threading.Thread(
                target=self._run_task, args=(task,), name=f"task-{task_id}", daemon=True
            ).start()

    def _run_task(self, task: dict) -> None:
        task_id = task.get("id")
        try:
            self._task_handler(task)
        except Exception as exc:
            log.error("task_handler_error", task_id=task_id, error=str(exc))
        finally:
            with self._inflight_lock:
                self._inflight.discard(task_id)


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
