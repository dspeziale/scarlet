"""Podman runtime: info, containers, images, registries, logs, stats."""

from __future__ import annotations

import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..context import AppContext
from ..errors import AppError, ConfirmationRequired, ValidationFailed
from ..images import podman_image_config
from ..security.rbac import Perm
from ..security.users import Session
from .deps import Audited, audited, get_ctx, require

router = APIRouter(prefix="/podman", tags=["podman"])
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,254}$")


def _id(value: str) -> str:
    if not ID_RE.match(value) or ".." in value:
        raise ValidationFailed("invalid container or image identifier", params={"field": "id"})
    return value


@router.get("/info")
def info(_: Session = Depends(require(Perm.PODMAN_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return ctx.podman.info()


@router.get("/containers")
def containers(all: bool = True, _: Session = Depends(require(Perm.PODMAN_READ)),
               ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    items = ctx.podman.list_containers(all)
    return {"items": items, "count": len(items)}


@router.get("/containers/{cid}")
def container(cid: str, _: Session = Depends(require(Perm.PODMAN_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    data = ctx.podman.inspect_container(_id(cid))
    # Environment variables can contain credentials: mask values with sensitive names.
    env = (data.get("Config") or {}).get("Env") or []
    masked = []
    for e in env:
        k = e.partition("=")[0]
        masked.append(f"{k}=<hidden>" if re.search(r"(PASSWORD|SECRET|TOKEN|KEY)", k, re.I) else e)
    if data.get("Config"):
        data["Config"]["Env"] = masked
    return {"inspect": data}


@router.get("/containers/{cid}/logs")
def container_logs(cid: str, tail: int = Query(500, ge=1, le=50000), timestamps: bool = True, download: bool = False,
                   _: Session = Depends(require(Perm.LOGS_READ)), ctx: AppContext = Depends(get_ctx),
                   audit: Audited = Depends(audited)) -> Any:  # fmt: skip
    tail = min(tail, ctx.settings.logs.max_tail_lines)
    lines = ctx.podman.container_logs(_id(cid), tail=tail, timestamps=timestamps)
    if download:
        audit("podman.logs_download", kind="PodmanContainer", name=cid)
        return PlainTextResponse("\n".join(lines) + "\n",
                                 headers={"Content-Disposition": f'attachment; filename="podman_{cid[:40]}.log"'})  # fmt: skip
    return {"lines": lines, "count": len(lines), "truncated": len(lines) >= tail}


class ActionBody(BaseModel):
    action: Literal["start", "stop", "restart"]
    confirm: str | None = Field(None, max_length=255)


@router.post("/containers/{cid}/action")
def container_action(cid: str, body: ActionBody, _: Session = Depends(require(Perm.PODMAN_OPERATE)),
                     ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    _id(cid)
    if body.action == "stop":
        name = ctx.podman.inspect_container(cid).get("Name", cid).lstrip("/")
        if body.confirm != name:
            raise ConfirmationRequired(f"type '{name}' to confirm stopping the container",
                                       params={"expected": name, "risk": "medium"})  # fmt: skip
    try:
        ctx.podman.container_action(cid, body.action)
    except AppError as exc:
        audit(f"podman.container.{body.action}", result="failure", kind="PodmanContainer", name=cid,
              detail={"error": exc.message})  # fmt: skip
        raise
    audit(f"podman.container.{body.action}", kind="PodmanContainer", name=cid)
    return {"ok": True}


@router.delete("/containers/{cid}")
def remove_container(cid: str, confirm: str | None = Query(None, max_length=255), force: bool = False,
                     _: Session = Depends(require(Perm.PODMAN_MANAGE)), ctx: AppContext = Depends(get_ctx),
                     audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    name = ctx.podman.inspect_container(_id(cid)).get("Name", cid).lstrip("/")
    if confirm != name:
        raise ConfirmationRequired(f"type '{name}' to confirm removing the container",
                                   params={"expected": name, "risk": "high"})  # fmt: skip
    ctx.podman.remove_container(cid, force=force)
    audit("podman.container.remove", kind="PodmanContainer", name=name, detail={"force": force})
    return {"ok": True}


@router.get("/images")
def images(_: Session = Depends(require(Perm.PODMAN_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    items = ctx.podman.list_images()
    return {"items": items, "count": len(items)}


@router.get("/images/{iid:path}/config")
def image_config(iid: str, _: Session = Depends(require(Perm.PODMAN_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    from ..images import config_risks

    data = ctx.podman.inspect_image(_id(iid))
    desc = podman_image_config(data)
    return {"config": desc, "risks": config_risks(desc), "size": data.get("Size"), "tags": data.get("RepoTags") or []}


class PullBody(BaseModel):
    reference: str = Field(min_length=1, max_length=512)


@router.post("/images/pull")
def pull(body: PullBody, _: Session = Depends(require(Perm.PODMAN_MANAGE)), ctx: AppContext = Depends(get_ctx),
         audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ref = _id(body.reference.strip())
    try:
        res = ctx.podman.pull_image(ref)
    except AppError as exc:
        audit("podman.image.pull", result="failure", kind="PodmanImage", name=ref, detail={"error": exc.message})
        raise
    audit("podman.image.pull", kind="PodmanImage", name=ref)
    return res


@router.delete("/images/{iid:path}")
def remove_image(iid: str, confirm: str | None = Query(None, max_length=255), force: bool = False,
                 _: Session = Depends(require(Perm.PODMAN_MANAGE)), ctx: AppContext = Depends(get_ctx),
                 audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    _id(iid)
    if confirm != iid:
        raise ConfirmationRequired(f"type '{iid}' to confirm removing the image", params={"expected": iid, "risk": "medium"})
    ctx.podman.remove_image(iid, force=force)
    audit("podman.image.remove", kind="PodmanImage", name=iid, detail={"force": force})
    return {"ok": True}


@router.get("/registries")
def registries(_: Session = Depends(require(Perm.PODMAN_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    info = ctx.podman.info()
    if not info.get("connected"):
        return {"connected": False, "error": info.get("error"), "search": [], "configured": {}}
    regs = info.get("registries") or {}
    images = ctx.podman.list_images()
    usage: dict[str, int] = {}
    for i in images:
        for t in i["tags"]:
            host = t.split("/", 1)[0] if "/" in t and ("." in t.split("/", 1)[0] or ":" in t.split("/", 1)[0]) else "docker.io"
            usage[host] = usage.get(host, 0) + 1
    return {"connected": True, "search": regs.get("search") or [], "configured": regs.get("configured") or {},
            "imagesByRegistry": usage}  # fmt: skip


@router.get("/stats")
def stats(_: Session = Depends(require(Perm.PODMAN_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return {"items": ctx.podman.stats()}
