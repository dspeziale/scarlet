"""First-run installation wizard API.

Available only while no user exists. Every call must carry the one-time setup token
(printed by install.sh / `pkm-admin setup-token`) in the X-Setup-Token header, so that
nobody who merely reaches the port can claim the installation.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import __version__
from ..audit import AuditContext
from ..config import KubernetesConfig, MonitoringConfig, PodmanConfig
from ..context import AppContext
from ..errors import Conflict, Forbidden, RateLimited
from ..k8s.live import LiveKubernetes
from ..monitoring import Prometheus
from ..podman.client import LivePodman
from ..security.users import SETUP_TOKEN_KEY, check_setup_token
from .deps import client_ip, get_ctx

router = APIRouter(prefix="/setup", tags=["setup"])


def setup_guard(request: Request, ctx: AppContext = Depends(get_ctx)) -> AppContext:
    if ctx.users.count() > 0:
        raise Conflict("the application is already configured", params={"reason": "setup_done"})
    ip = client_ip(request, ctx)
    if not ctx.login_limiter.hit(f"setup:{ip}"):
        raise RateLimited("too many attempts", params={"retryAfter": ctx.login_limiter.retry_after(f"setup:{ip}")})
    if not check_setup_token(ctx.db, request.headers.get("x-setup-token")):
        raise Forbidden("invalid setup token", params={"reason": "setup_token"})
    return ctx


class K8sTest(BaseModel):
    enabled: bool = True
    kubeconfig: str | None = Field(None, max_length=1024)
    context: str | None = Field(None, max_length=253)
    in_cluster: bool = False


class PodmanTest(BaseModel):
    enabled: bool = True
    url: str = Field("unix:///run/podman/podman.sock", max_length=1024)


class PromTest(BaseModel):
    prometheus_url: str | None = Field(None, max_length=1024)


class AdminBody(BaseModel):
    username: str = Field(min_length=2, max_length=63)
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field("", max_length=120)
    email: str = Field("", max_length=200)


class CompleteBody(BaseModel):
    admin: AdminBody
    language: Literal["it", "en"] = "it"
    kubernetes: K8sTest | None = None
    podman: PodmanTest | None = None
    monitoring: PromTest | None = None
    backup_retention_count: int | None = Field(None, ge=1, le=1000)


@router.get("/status")
def status(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    required = ctx.users.count() == 0
    return {"setupRequired": required, "tokenIssued": bool(ctx.db.get_state(SETUP_TOKEN_KEY)), "mode": ctx.settings.mode}


@router.post("/verify-token")
def verify_token(ctx: AppContext = Depends(setup_guard)) -> dict[str, Any]:
    return {"ok": True}


@router.get("/system-check")
def system_check(ctx: AppContext = Depends(setup_guard)) -> dict[str, Any]:
    s = ctx.settings
    data_dir = Path(s.database.path).parent
    usage = shutil.disk_usage(data_dir)
    os_release: dict[str, str] = {}
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            os_release[k] = v.strip('"')
    except OSError:
        pass
    is_ol = os_release.get("ID") == "ol"
    checks = [
        {"id": "os", "status": "ok" if is_ol and os_release.get("VERSION_ID", "").startswith("9") else "warn",
         "params": {"name": os_release.get("PRETTY_NAME") or platform.platform()}},
        {"id": "arch", "status": "ok" if platform.machine() in ("x86_64", "AMD64") else "warn",
         "params": {"arch": platform.machine()}},
        {"id": "python", "status": "ok" if sys.version_info >= (3, 11) else "fail",
         "params": {"version": platform.python_version()}},
        {"id": "data_dir", "status": "ok" if os.access(data_dir, os.W_OK) else "fail", "params": {"path": str(data_dir)}},
        {"id": "disk_space", "status": "ok" if usage.free > 1 << 30 else "warn", "params": {"freeBytes": usage.free}},
        {"id": "tls", "status": "ok" if s.server.tls_enabled else ("ok" if s.server.trusted_proxies else "warn"),
         "params": {"enabled": s.server.tls_enabled, "proxy": bool(s.server.trusted_proxies)}},
        {"id": "mode", "status": "warn" if s.is_demo else "ok", "params": {"mode": s.mode}},
    ]  # fmt: skip
    return {"checks": checks, "version": __version__, "config": {
        "kubernetes": s.kubernetes.model_dump(), "podman": s.podman.model_dump(),
        "monitoring": {"prometheus_url": s.monitoring.prometheus_url},
        "backup": {"directory": s.backup.directory, "retention_count": s.backup.retention_count},
        "tls": {"enabled": s.server.tls_enabled, "cert": s.server.tls_cert}, "server": {"host": s.server.host,
                                                                                      "port": s.server.port}}}  # fmt: skip


def _k8s_cfg(ctx: AppContext, body: K8sTest) -> KubernetesConfig:
    return ctx.settings.kubernetes.model_copy(update=body.model_dump())


@router.post("/test-kubernetes")
def test_kubernetes(body: K8sTest, ctx: AppContext = Depends(setup_guard)) -> dict[str, Any]:
    if ctx.demo:
        return ctx.k8s.info()
    if not body.enabled:
        return {"connected": False, "skipped": True}
    prov = LiveKubernetes(_k8s_cfg(ctx, body))
    try:
        info = prov.info()
        if info.get("connected"):
            # Read permission probe on a couple of core resources.
            from ..errors import AppError
            from ..k8s.kinds import KINDS

            perms = {}
            for key in ("nodes", "pods", "deployments", "events"):
                try:
                    prov.list(KINDS[key])
                    perms[key] = "ok"
                except AppError as exc:
                    perms[key] = exc.code
            info["permissions"] = perms
        return info
    finally:
        prov.close()


@router.post("/test-podman")
def test_podman(body: PodmanTest, ctx: AppContext = Depends(setup_guard)) -> dict[str, Any]:
    if ctx.demo:
        return ctx.podman.info()
    if not body.enabled:
        return {"connected": False, "skipped": True}
    prov = LivePodman(PodmanConfig(enabled=True, url=body.url, timeout=ctx.settings.podman.timeout))
    try:
        return prov.info()
    finally:
        prov.close()


@router.post("/test-prometheus")
def test_prometheus(body: PromTest, ctx: AppContext = Depends(setup_guard)) -> dict[str, Any]:
    if not body.prometheus_url:
        return {"ok": False, "skipped": True}
    from ..errors import AppError

    try:
        cfg = MonitoringConfig(prometheus_url=body.prometheus_url)
        return Prometheus(cfg).ping()
    except AppError as exc:
        return {"ok": False, "error": {"code": exc.code, "message": exc.message, "details": exc.details}}
    except ValueError as exc:
        return {"ok": False, "error": {"code": "validation_failed", "message": str(exc)}}


@router.post("/complete")
def complete(body: CompleteBody, request: Request, ctx: AppContext = Depends(setup_guard)) -> dict[str, Any]:
    user = ctx.users.create(body.admin.username, body.admin.password, "admin", display_name=body.admin.display_name,
                            email=body.admin.email, language=body.language)  # fmt: skip
    actor = body.admin.username
    changed = []

    def save(section: str, values: dict[str, Any]) -> None:
        # Store only what differs from config.yaml: unchanged defaults stay owned by the file.
        current = getattr(ctx.settings, section).model_dump()
        diff = {k: v for k, v in values.items() if current.get(k) != v}
        if diff:
            ctx.runtime.update(section, diff, actor)
            changed.append(section)

    if body.kubernetes is not None and not ctx.demo:
        save("kubernetes", body.kubernetes.model_dump())
    if body.podman is not None and not ctx.demo:
        save("podman", body.podman.model_dump())
    if body.monitoring is not None:
        save("monitoring", {"prometheus_url": body.monitoring.prometheus_url or None})
    if body.backup_retention_count:
        save("backup", {"retention_count": body.backup_retention_count})
    for section in changed:
        ctx.apply_settings(section)
    ctx.db.set_state(SETUP_TOKEN_KEY, None)
    from ..db import iso

    ctx.db.set_state("setup_completed_at", iso())
    ctx.audit.record(AuditContext(user.id, user.username, client_ip(request, ctx), request.headers.get("user-agent", "")),
                     "setup.completed", detail={"sections": changed})  # fmt: skip
    return {"ok": True, "user": user.public()}
