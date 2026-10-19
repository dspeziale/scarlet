"""Health checks of Scarlet and its dependencies. States: healthy | degraded | unhealthy."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from .db import parse_iso, utcnow

RANK = {"healthy": 0, "degraded": 1, "unhealthy": 2}


def _check(cid: str, fn: Any, *, optional: bool = False) -> dict[str, Any]:
    start = time.monotonic()
    try:
        status, message, params = fn()
    except Exception as exc:  # a failing check must never break the health page
        status, message, params = "unhealthy", f"{type(exc).__name__}: {exc}", {}
    return {"id": cid, "status": status, "message": message, "params": params, "optional": optional,
            "latencyMs": int((time.monotonic() - start) * 1000)}  # fmt: skip


def run_checks(ctx: Any) -> dict[str, Any]:
    settings = ctx.settings
    started = ctx.started_at

    def backend():
        return "healthy", "running", {"uptimeSeconds": int(time.time() - started)}

    def database():
        ctx.db.ping()
        return "healthy", "ok", {"schemaVersion": ctx.db.schema_version(), "path": settings.database.path}

    def kubernetes():
        if not settings.kubernetes.enabled and not settings.is_demo:
            return "degraded", "disabled", {"configured": False}
        info = ctx.k8s.info()
        if info.get("connected"):
            return "healthy", "connected", {"version": (info.get("version") or {}).get("gitVersion"),
                                            "context": info.get("context")}  # fmt: skip
        err = info.get("error") or {}
        return "unhealthy", err.get("message", "not connected"), {"code": err.get("code"), "details": err.get("details")}

    def podman():
        if not settings.podman.enabled and not settings.is_demo:
            return "degraded", "disabled", {"configured": False}
        info = ctx.podman.info()
        if info.get("connected"):
            return "healthy", "connected", {"version": info.get("version"), "rootless": info.get("rootless")}
        err = info.get("error") or {}
        return "unhealthy", err.get("message", "not connected"), {"code": err.get("code"), "details": err.get("details")}

    def storage():
        path = Path(settings.database.path).parent
        usage = shutil.disk_usage(path)
        free = usage.free / usage.total if usage.total else 0
        status = "healthy" if free > 0.10 else ("degraded" if free > 0.03 else "unhealthy")
        return status, "ok" if status == "healthy" else "low_disk_space", {
            "path": str(path), "freeBytes": usage.free, "totalBytes": usage.total, "freeRatio": round(free, 4)}

    def configuration():
        problems = []
        if settings.environment == "production" and not settings.server.tls_enabled and not settings.server.trusted_proxies:
            problems.append("no_tls")
        if settings.environment == "production" and settings.server.host in ("0.0.0.0", "::") and \
                not settings.server.tls_enabled:  # noqa: S104  # fmt: skip
            problems.append("plain_http_exposed")
        if settings.is_demo:
            problems.append("demo_mode")
        return ("degraded" if problems else "healthy"), ("issues" if problems else "ok"), {
            "problems": problems, "configFile": settings.config_file, "mode": settings.mode,
            "environment": settings.environment}

    def metrics_server():
        if not ctx.k8s.info().get("connected"):
            return "degraded", "kubernetes_unavailable", {}
        m = ctx.k8s.node_metrics()
        return ("healthy", "available", {}) if m is not None else ("degraded", "not_installed", {})

    def prometheus():
        if not settings.monitoring.prometheus_url:
            return "degraded", "not_configured", {}
        res = ctx.prometheus.ping()
        return "healthy", "connected", res

    def backup():
        last = ctx.backups.last()
        if not last:
            return "degraded", "never", {}
        age = (utcnow() - (parse_iso(last["created_at"]) or utcnow())).total_seconds()
        return ("healthy" if age < 2 * 86400 else "degraded"), ("ok" if age < 2 * 86400 else "old"), {
            "last": last["created_at"], "ageSeconds": int(age), "file": last["filename"]}

    checks = [
        _check("backend", backend),
        _check("database", database),
        _check("kubernetes", kubernetes),
        _check("podman", podman, optional=True),
        _check("storage", storage),
        _check("configuration", configuration),
        _check("metrics_server", metrics_server, optional=True),
        _check("prometheus", prometheus, optional=True),
        _check("backup", backup, optional=True),
    ]
    worst = "healthy"
    for c in checks:
        effective = c["status"]
        if c["optional"] and effective == "unhealthy":
            effective = "degraded"
        if RANK[effective] > RANK[worst]:
            worst = effective
    return {"status": worst, "checks": checks, "checkedAt": utcnow().isoformat(timespec="seconds")}
