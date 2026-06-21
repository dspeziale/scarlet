"""
Autonomous scan scheduler.

Periodically fetches the per-probe scan schedule from the server
(/probes/<id>/scan-config) and runs network/wifi/ble scans on their
configured intervals, posting results to /probes/<id>/scan-results.

Config shape (per scan type):
    {"enabled": bool, "interval_sec": int, ...type-specific...}
"""

from __future__ import annotations

import threading
import time
from typing import Callable

import httpx
import structlog

log = structlog.get_logger(__name__)

_SCAN_TYPES = ("network_discovery", "wifi_scan", "ble_scan")
_CONFIG_TTL = 30  # re-fetch the schedule at most every 30s


class SchedulerWorker(threading.Thread):
    def __init__(
        self,
        server_url: str,
        probe_id: str,
        http_client: httpx.Client,
        run_scan: Callable[[str, dict], dict],
        tick: int = 10,
    ) -> None:
        super().__init__(name="scheduler", daemon=True)
        self._cfg_url = f"{server_url}/api/v1/probes/{probe_id}/scan-config"
        self._res_url = f"{server_url}/api/v1/probes/{probe_id}/scan-results"
        self._http = http_client
        self._run_scan = run_scan
        self._tick = tick
        self._stop = threading.Event()
        self._config: dict = {}
        self._config_fetched_at = 0.0
        self._last_run: dict[str, float] = {}

    def run(self) -> None:
        log.info("scheduler_started", tick=self._tick)
        while not self._stop.is_set():
            try:
                self._cycle()
            except Exception:
                log.exception("scheduler_error")
            self._stop.wait(self._tick)

    def shutdown(self) -> None:
        self._stop.set()

    # ── Internals ────────────────────────────────────────────────────────────

    def _fetch_config(self) -> None:
        now = time.monotonic()
        if self._config and (now - self._config_fetched_at) < _CONFIG_TTL:
            return
        try:
            resp = self._http.get(self._cfg_url, timeout=10)
            if resp.status_code == 200:
                self._config = resp.json() or {}
                self._config_fetched_at = now
        except Exception as exc:
            log.debug("scheduler_config_fetch_failed", error=str(exc))

    def _cycle(self) -> None:
        self._fetch_config()
        now = time.monotonic()
        for stype in _SCAN_TYPES:
            entry = self._config.get(stype) or {}
            if not entry.get("enabled"):
                continue
            interval = max(30, int(entry.get("interval_sec", 3600)))
            last = self._last_run.get(stype, 0.0)
            if last and (now - last) < interval:
                continue
            # Run the scan (may be slow — that's fine, this is a dedicated thread).
            log.info("autoscan_run", scan_type=stype)
            self._last_run[stype] = now
            try:
                result = self._run_scan(stype, entry)
            except Exception as exc:
                log.warning("autoscan_failed", scan_type=stype, error=str(exc))
                continue
            try:
                self._http.post(self._res_url, json={"type": stype, "result": result}, timeout=20)
            except Exception as exc:
                log.warning("autoscan_post_failed", scan_type=stype, error=str(exc))
