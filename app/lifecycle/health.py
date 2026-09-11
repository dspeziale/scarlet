"""Health checking with retries, built on top of runtime adapters."""

from __future__ import annotations

import time

from app.deployment.domain import DesiredApplicationState, HealthSpec
from app.models.enums import HealthStatus
from app.runtimes.base import HealthResult, RuntimeAdapter, RuntimeContext


def health_spec_from_application(application, manifest: dict | None = None) -> HealthSpec:
    """Merge application-level defaults with the manifest healthcheck block."""
    manifest_hc = (manifest or {}).get("healthcheck") or {}
    check_type = (manifest_hc.get("type") or application.healthcheck_type or "container_status").upper()
    command = manifest_hc.get("command") or application.healthcheck_command
    argv: tuple[str, ...] = ()
    if command:
        import shlex

        argv = tuple(shlex.split(command))
    path = manifest_hc.get("path") or application.healthcheck_url or "/health"
    return HealthSpec(
        check_type=check_type,
        path=path,
        port=manifest_hc.get("port") or application.healthcheck_port or application.default_port,
        expected_status=int(manifest_hc.get("expected_status") or application.healthcheck_expected_status or 200),
        timeout=int(manifest_hc.get("timeout") or application.healthcheck_timeout or 10),
        retries=int(manifest_hc.get("retries") or application.healthcheck_retries or 5),
        interval=int(manifest_hc.get("interval") if manifest_hc.get("interval") is not None else application.healthcheck_interval or 3),
        command=argv,
    )


class HealthChecker:
    def __init__(self, adapter: RuntimeAdapter, sleep=time.sleep) -> None:
        self.adapter = adapter
        self._sleep = sleep

    def check(self, ctx: RuntimeContext, spec: HealthSpec, desired: DesiredApplicationState | None = None, *, retries: int | None = None) -> HealthResult:
        attempts = max(1, retries if retries is not None else spec.retries)
        t0 = time.monotonic()
        last: HealthResult | None = None
        for attempt in range(1, attempts + 1):
            try:
                last = self.adapter.health(ctx, spec, desired)
            except Exception as exc:  # noqa: BLE001 - probe errors are reported, not raised
                last = HealthResult(HealthStatus.UNHEALTHY, f"Health probe error: {exc}")
            last.attempts = attempt
            ctx.log("INFO" if last.healthy else "WARNING", f"Health check attempt {attempt}/{attempts}: {last.status.value} - {last.message}")
            if last.healthy:
                break
            if attempt < attempts and spec.interval:
                self._sleep(spec.interval)
        assert last is not None
        last.duration_seconds = round(time.monotonic() - t0, 3)
        return last
