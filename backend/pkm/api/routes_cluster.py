"""Dashboard, operations center, notifications, global search, system status, health and live events."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from .. import API_VERSION, __version__
from ..context import AppContext
from ..errors import AppError
from ..health import run_checks
from ..k8s.diagnostics import summary_counts
from ..k8s.kinds import KINDS
from ..k8s.naming import validate_name
from ..security.rbac import Perm, has_perm
from ..security.users import Session
from .deps import Audited, audited, current_session, get_ctx, require

router = APIRouter(tags=["cluster"])


@router.get("/system/info")
def system_info(ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    """Public: what the login page needs (no cluster data)."""
    return {"appName": ctx.settings.app_name, "version": __version__, "apiVersion": API_VERSION,
            "mode": ctx.settings.mode, "environment": ctx.settings.environment,
            "setupRequired": ctx.users.count() == 0, "languages": ["it", "en"]}  # fmt: skip


@router.get("/system/status")
def system_status(_: Session = Depends(current_session), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    k = ctx.k8s.info()
    p = ctx.podman.info()
    return {
        "appName": ctx.settings.app_name, "version": __version__, "apiVersion": API_VERSION,
        "mode": ctx.settings.mode, "environment": ctx.settings.environment,
        "kubernetes": {"connected": k.get("connected"), "context": k.get("context"), "server": k.get("server"),
                       "version": (k.get("version") or {}).get("gitVersion"), "error": k.get("error")},
        "podman": {"connected": p.get("connected"), "version": p.get("version"), "apiVersion": p.get("apiVersion"),
                   "rootless": p.get("rootless"), "endpoint": p.get("endpoint"), "error": p.get("error")},
        "monitor": ctx.last_monitor,
        "prometheus": bool(ctx.settings.monitoring.prometheus_url),
    }  # fmt: skip


@router.get("/health")
def health(_: Session = Depends(require(Perm.MONITORING_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return run_checks(ctx)


@router.get("/cluster/overview")
def overview(_: Session = Depends(require(Perm.CLUSTER_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    data = ctx.k8s.overview()
    data["notifications"] = ctx.notifications.counts()
    return data


@router.get("/cluster/issues")
def issues(namespace: str | None = Query(None, max_length=63), severity: str | None = None,
           _: Session = Depends(require(Perm.CLUSTER_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    if namespace:
        validate_name(namespace, "namespace")
    items, partial = ctx.k8s.issues(namespace)
    if namespace:
        # Node-level issues are cluster scoped: they are listed only without a namespace filter.
        items = [i for i in items if i.namespace == namespace]
    counts = summary_counts(items)
    if severity:
        items = [i for i in items if i.severity == severity]
    active = {n["fingerprint"]: n for n in ctx.notifications.list(status="active", limit=500)["items"]}
    acks = {fp: n for fp, n in active.items() if n["status"] == "acknowledged"}
    out = []
    for i in items:
        d = i.to_dict()
        ack = acks.get(i.id)
        d["acknowledged"] = {"by": ack["acknowledged_by"], "at": ack["acknowledged_at"], "notificationId": ack["id"]} if ack else None
        d["notificationId"] = active[i.id]["id"] if i.id in active else None
        out.append(d)
    return {"items": out, "counts": counts, "partial": partial}


# ---------------------------------------------------------------- notifications
@router.get("/notifications")
def notifications(status: Literal["open", "acknowledged", "resolved", "active"] | None = "active",
                  severity: Literal["INFO", "WARNING", "ERROR", "CRITICAL"] | None = None,
                  q: str | None = Query(None, max_length=200), limit: int = Query(100, ge=1, le=500),
                  offset: int = Query(0, ge=0), _: Session = Depends(require(Perm.CLUSTER_READ)),
                  ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    res = ctx.notifications.list(status=status, severity=severity, q=q, limit=limit, offset=offset)
    res["counts"] = ctx.notifications.counts()
    return res


@router.post("/notifications/{nid}/ack")
def ack(nid: int, _: Session = Depends(require(Perm.NOTIFICATIONS_ACK)), ctx: AppContext = Depends(get_ctx),
        audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.notifications.set_ack(nid, audit.session.user.username if audit.session else "", True)
    audit("notification.ack", kind=res["resource_kind"], name=res["resource_name"], namespace=res["namespace"],
          detail={"reason": res["reason"], "id": nid})  # fmt: skip
    ctx.events.publish({"type": "notifications", "counts": ctx.notifications.counts()})
    return res


@router.post("/notifications/{nid}/unack")
def unack(nid: int, _: Session = Depends(require(Perm.NOTIFICATIONS_ACK)), ctx: AppContext = Depends(get_ctx),
          audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.notifications.set_ack(nid, "", False)
    audit("notification.unack", kind=res["resource_kind"], name=res["resource_name"], namespace=res["namespace"],
          detail={"id": nid})  # fmt: skip
    ctx.events.publish({"type": "notifications", "counts": ctx.notifications.counts()})
    return res


@router.post("/notifications/refresh")
async def refresh_notifications(_: Session = Depends(require(Perm.CLUSTER_READ)),
                                ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    changed = await asyncio.to_thread(ctx.monitor_once)
    counts = ctx.notifications.counts()
    if changed:
        ctx.events.publish({"type": "notifications", "counts": counts})
    return {"changed": changed, "counts": counts}


# ---------------------------------------------------------------- search
_SEARCH_KINDS = ["namespaces", "nodes", "pods", "deployments", "statefulsets", "daemonsets", "jobs", "cronjobs",
                 "services", "ingresses", "configmaps", "secrets", "persistentvolumeclaims", "persistentvolumes"]  # fmt: skip


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=100), session: Session = Depends(require(Perm.CLUSTER_READ)),
           ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    needle = q.lower().strip()
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    if ctx.k8s.info().get("connected"):
        for key in _SEARCH_KINDS:
            try:
                items = ctx.k8s.list_raw(KINDS[key])
            except AppError as exc:
                errors.append(f"{key}: {exc.code}")
                continue
            for o in items:
                meta = o.get("metadata") or {}
                name = meta.get("name", "")
                labels = " ".join(f"{k}={v}" for k, v in (meta.get("labels") or {}).items())
                images = ""
                if key in ("pods", "deployments", "statefulsets", "daemonsets"):
                    spec = o.get("spec") or {}
                    tmpl = spec.get("template", {}).get("spec") if key != "pods" else spec
                    images = " ".join(c.get("image", "") for c in (tmpl or {}).get("containers") or [])
                hay = f"{name} {labels} {images}".lower()
                if needle in hay:
                    results.append({"type": "k8s", "kind": KINDS[key].kind, "key": key, "name": name,
                                    "namespace": meta.get("namespace"), "match": "name" if needle in name.lower()
                                    else ("image" if needle in images.lower() else "label")})  # fmt: skip
        try:
            for e in ctx.k8s.list_raw(KINDS["events"]):
                if needle in (e.get("message") or "").lower() or needle in (e.get("reason") or "").lower():
                    inv = e.get("involvedObject") or {}
                    results.append({"type": "event", "kind": inv.get("kind"), "name": inv.get("name"),
                                    "namespace": inv.get("namespace"), "reason": e.get("reason"),
                                    "message": (e.get("message") or "")[:200], "eventType": e.get("type")})  # fmt: skip
        except AppError as exc:
            errors.append(f"events: {exc.code}")
    if has_perm(session.user.role, Perm.PODMAN_READ) and ctx.podman.info().get("connected"):
        try:
            for c in ctx.podman.list_containers(True):
                if needle in (c["name"] or "").lower() or needle in (c["image"] or "").lower() or needle in c["id"]:
                    results.append({"type": "podman_container", "name": c["name"], "id": c["id"], "image": c["image"],
                                    "state": c["state"]})  # fmt: skip
            for i in ctx.podman.list_images():
                if any(needle in t.lower() for t in i["tags"]) or needle in i["id"]:
                    results.append({"type": "podman_image", "name": (i["tags"] or [i["id"]])[0], "id": i["id"]})
        except AppError as exc:
            errors.append(f"podman: {exc.code}")
    results.sort(key=lambda r: (r.get("name", "").lower() != needle, not r.get("name", "").lower().startswith(needle)))
    return {"items": results[:100], "total": len(results), "errors": errors}


# ---------------------------------------------------------------- live events (SSE)
@router.get("/stream")
async def stream(request: Request, _: Session = Depends(current_session),
                 ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:  # fmt: skip
    q = ctx.events.subscribe()

    async def gen():  # type: ignore[no-untyped-def]
        try:
            yield f"event: hello\ndata: {json.dumps({'counts': ctx.notifications.counts()})}\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    data = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"data: {data}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            ctx.events.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # fmt: skip


@router.get("/operations")
def operations(_: Session = Depends(require(Perm.CLUSTER_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return {"items": ctx.operations.list()}


@router.get("/operations/{op_id}")
def operation(op_id: str, _: Session = Depends(require(Perm.CLUSTER_READ)),
              ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    return ctx.operations.get(op_id).public()


@router.post("/operations/{op_id}/cancel")
def cancel_operation(op_id: str, session: Session = Depends(current_session), ctx: AppContext = Depends(get_ctx),
                     audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    op = ctx.operations.get(op_id)
    from ..errors import Forbidden

    if op.user != session.user.username and session.user.role != "admin":
        raise Forbidden("only the user who started the operation or an administrator can cancel it")
    ctx.operations.cancel(op_id)
    audit("operation.cancel", kind=op.kind, name=op.target, detail={"id": op_id})
    return op.public()
