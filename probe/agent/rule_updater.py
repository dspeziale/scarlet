"""
Polls the server for IDS rule updates and applies them to Suricata.

Flow:
1. GET /api/v1/probes/<id>/ids/rules  →  raw .rules text + version header
2. If version changed → write to rules_path, send SIGUSR2 to Suricata
3. Sleep RULE_CHECK_INTERVAL, repeat
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

import httpx
import structlog

log = structlog.get_logger(__name__)


class RuleUpdater(threading.Thread):
    def __init__(
        self,
        server_url: str,
        probe_id: str,
        rules_path: Path,
        check_interval: int,
        http_client: httpx.Client,
        suricata_reload_fn,
    ) -> None:
        super().__init__(name="rule-updater", daemon=True)
        self._url = f"{server_url}/api/v1/probes/{probe_id}/ids/rules"
        self._rules_path = rules_path
        self._interval = check_interval
        self._http = http_client
        self._reload = suricata_reload_fn
        self._current_version: Optional[str] = None
        self._stop = threading.Event()

    def run(self) -> None:
        log.info("rule_updater_started", interval=self._interval)
        while not self._stop.is_set():
            try:
                self._check_and_apply()
            except Exception:
                log.exception("rule_updater_error")
            self._stop.wait(self._interval)

    def shutdown(self) -> None:
        self._stop.set()

    def _check_and_apply(self) -> None:
        headers = {}
        if self._current_version:
            headers["If-None-Match"] = self._current_version

        resp = self._http.get(self._url, headers=headers, timeout=15)

        if resp.status_code == 304:
            log.debug("rules_up_to_date", version=self._current_version)
            return

        if resp.status_code == 404:
            log.info("no_ruleset_assigned")
            return

        resp.raise_for_status()

        new_version = resp.headers.get("X-Ruleset-Version", "unknown")
        content = resp.text

        if new_version == self._current_version:
            return

        self._rules_path.parent.mkdir(parents=True, exist_ok=True)
        self._rules_path.write_text(content)
        log.info(
            "rules_updated",
            previous=self._current_version,
            current=new_version,
            rules_count=content.count("\nalert ") + (1 if content.startswith("alert ") else 0),
        )
        self._current_version = new_version
        self._reload()
