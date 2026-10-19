"""Application context: wires configuration, storage, integrations and background monitoring."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from .audit import AuditService
from .backup import BackupService
from .config import Settings
from .db import Database
from .errors import AppError
from .k8s import diagnostics
from .k8s.service import KubernetesService, build_provider
from .logging_setup import set_level
from .monitoring import Prometheus
from .notifications import NotificationService
from .operations import OperationManager
from .podman.client import PodmanProvider, build_podman
from .runtime_settings import RuntimeSettings
from .security.ratelimit import RateLimiter
from .security.users import UserService

log = logging.getLogger("pkm.context")


class EventBus:
    """Fan-out of small JSON events to SSE subscribers (same event loop)."""

    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[str]] = set()

    def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        self._subs.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        data = json.dumps(event, default=str)
        for q in list(self._subs):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    @property
    def subscribers(self) -> int:
        return len(self._subs)


class AppContext:
    def __init__(self, base: Settings) -> None:
        self.base_settings = base
        self.started_at = time.time()
        self.db = Database(base.database.path)
        self.db.migrate()
        self.runtime = RuntimeSettings(self.db, base)
        self.settings = self.runtime.effective()
        set_level(self.settings.logging.level)
        self.users = UserService(self.db, self.settings.auth)
        self.audit = AuditService(self.db)
        self.notifications = NotificationService(self.db)
        self.operations = OperationManager()
        self.k8s = KubernetesService(build_provider(self.settings), self.settings.kubernetes)
        self.podman: PodmanProvider = build_podman(self.settings)
        self.prometheus = Prometheus(self.settings.monitoring)
        self.backups = BackupService(self.db, self.settings.backup.directory, base.config_file)
        self.login_limiter = RateLimiter(self.settings.rate_limit.login_per_minute)
        self.api_limiter = RateLimiter(self.settings.rate_limit.api_per_minute)
        self.events = EventBus()
        self.log_streams = asyncio.Semaphore(self.settings.logs.max_concurrent_streams)
        self.last_monitor: dict[str, Any] = {"at": None, "error": None, "issues": 0}
        self._monitor_task: asyncio.Task[None] | None = None
        self._last_housekeeping = 0.0

    @property
    def demo(self) -> bool:
        return self.settings.is_demo

    # ---------------------------------------------------------------- settings reload
    def apply_settings(self, section: str) -> None:
        self.settings = self.runtime.effective()
        if section == "kubernetes":
            self.k8s.replace_provider(build_provider(self.settings), self.settings.kubernetes)
        elif section == "podman":
            old = self.podman
            self.podman = build_podman(self.settings)
            old.close()
        elif section == "monitoring":
            self.prometheus = Prometheus(self.settings.monitoring)
        elif section == "logging":
            set_level(self.settings.logging.level)
        elif section == "auth":
            self.users.cfg = self.settings.auth
        elif section == "backup":
            self.backups = BackupService(self.db, self.settings.backup.directory, self.base_settings.config_file)

    # ---------------------------------------------------------------- monitor
    def start_monitor(self) -> None:
        self._monitor_task = asyncio.get_running_loop().create_task(self._monitor_loop(), name="pkm-monitor")

    async def stop(self) -> None:
        self.operations.cancel_all()
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except (asyncio.CancelledError, Exception):  # noqa: S110
                pass
        self.k8s.close()
        self.podman.close()

    async def _monitor_loop(self) -> None:
        await asyncio.sleep(2)
        while True:
            try:
                changed = await asyncio.to_thread(self.monitor_once)
                if changed:
                    self.events.publish({"type": "notifications", "counts": self.notifications.counts()})
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("monitor iteration failed")
            await asyncio.sleep(self.settings.monitoring.poll_interval_seconds)

    def monitor_once(self) -> bool:
        """One detection cycle. Returns True when the notification set changed."""
        system_items: list[dict[str, Any]] = []
        changed = False
        info = self.k8s.info()
        if info.get("connected"):
            try:
                issues, partial = self.k8s.issues()
                items = [{"fingerprint": i.id, "severity": i.severity, "reason": i.reason, "kind": i.kind,
                          "name": i.name, "namespace": i.namespace, "message": i.message,
                          "data": {"owner": i.owner, "node": i.node, "affected": i.affected, "guide": i.guide,
                                   "facts": i.facts, "likely_cause": i.likely_cause}}
                         for i in issues if i.severity != "INFO"]  # fmt: skip
                stats = self.notifications.sync("kubernetes", items)
                changed = any(stats.values())
                self.last_monitor = {"at": time.time(), "error": None, "issues": len(issues),
                                     "counts": diagnostics.summary_counts(issues), "partial": partial}  # fmt: skip
            except AppError as exc:
                self.last_monitor = {"at": time.time(), "error": exc.code, "issues": 0}
        elif self.settings.kubernetes.enabled or self.demo:
            err = info.get("error") or {}
            system_items.append({"fingerprint": "system:kubernetes", "severity": "CRITICAL",
                                 "reason": "KubernetesUnreachable", "kind": "System", "name": "kubernetes",
                                 "message": err.get("message", ""), "data": {"code": err.get("code")}})  # fmt: skip
        if self.settings.podman.enabled or self.demo:
            pinfo = self.podman.info()
            if not pinfo.get("connected"):
                err = pinfo.get("error") or {}
                system_items.append({"fingerprint": "system:podman", "severity": "WARNING",
                                     "reason": "PodmanUnreachable", "kind": "System", "name": "podman",
                                     "message": err.get("message", ""), "data": {"code": err.get("code")}})  # fmt: skip
        stats = self.notifications.sync("system", system_items)
        changed = changed or any(stats.values())
        self.housekeeping()
        return changed

    def housekeeping(self, force: bool = False) -> dict[str, int]:
        now = time.time()
        if not force and now - self._last_housekeeping < 3600:
            return {}
        self._last_housekeeping = now
        out = {
            "sessions": self.users.purge_expired_sessions(),
            "audit": self.audit.purge(self.settings.audit.retention_days),
            "notifications": self.notifications.purge_resolved(30),
        }
        if any(out.values()):
            log.info("housekeeping", extra=out)
        return out
