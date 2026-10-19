"""Kubernetes resources, operations, logs, YAML apply and guided deployment."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from .. import images as image_tools
from ..context import AppContext
from ..errors import (
    AppError,
    BadRequest,
    ConfirmationRequired,
    Forbidden,
    K8sNotFound,
    NotSupported,
    RateLimited,
    ValidationFailed,
)
from ..k8s import manifests
from ..k8s.kinds import HIGH_RISK_DELETE, KINDS, get_kind, kind_for_manifest
from ..k8s.naming import validate_name
from ..k8s.service import validate_manifest_shape
from ..k8s.summarize import controller_of
from ..security.rbac import Perm, has_perm
from ..security.users import Session
from .deps import Audited, audit_ctx, audited, current_session, get_ctx, require

router = APIRouter(tags=["kubernetes"])
MAX_YAML = 512 * 1024
MAX_DOCS = 50


def _ns(kind_key: str, namespace: str) -> str | None:
    kind = get_kind(kind_key)
    if not kind.namespaced:
        return None
    validate_name(namespace, "namespace")
    return namespace


def _check_name(name: str) -> str:
    return validate_name(name, "name", subdomain=True)


def _confirm(confirm: str | None, expected: str, *, what: str, params: dict[str, Any]) -> None:
    if confirm != expected:
        raise ConfirmationRequired(f"type '{expected}' to confirm: {what}",
                                   params={**params, "expected": expected})  # fmt: skip


# ---------------------------------------------------------------- reads
@router.get("/k8s/kinds")
def kinds(_: Session = Depends(require(Perm.CLUSTER_READ))) -> dict[str, Any]:
    return {"items": [k.public() for k in KINDS.values()]}


@router.get("/k8s/{kind}")
def list_resources(kind: str, namespace: str | None = Query(None, max_length=63),
                   labelSelector: str | None = Query(None, max_length=1024),
                   _: Session = Depends(require(Perm.CLUSTER_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    if namespace:
        validate_name(namespace, "namespace")
    return ctx.k8s.list_summaries(kind, namespace, labelSelector)


@router.get("/k8s/{kind}/{namespace}/{name}")
def get_resource(kind: str, namespace: str, name: str, reveal: bool = False,
                 session: Session = Depends(require(Perm.CLUSTER_READ)), ctx: AppContext = Depends(get_ctx),
                 audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ns = _ns(kind, namespace)
    _check_name(name)
    if reveal:
        if kind != "secrets":
            raise BadRequest("reveal is only meaningful for secrets")
        if not has_perm(session.user.role, Perm.SECRETS_READ_VALUES):
            audit("secret.reveal", result="denied", kind="Secret", name=name, namespace=ns)
            raise Forbidden("your role cannot read secret values", params={"permission": Perm.SECRETS_READ_VALUES.value})
        audit("secret.reveal", kind="Secret", name=name, namespace=ns)
    data = ctx.k8s.detail(kind, name, ns, reveal=reveal)
    data["yaml"] = yaml.safe_dump(data["object"], sort_keys=False, allow_unicode=True)
    return data


@router.get("/k8s/{kind}/{namespace}/{name}/events")
def resource_events(kind: str, namespace: str, name: str, _: Session = Depends(require(Perm.CLUSTER_READ)),
                    ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    return {"items": ctx.k8s.events_for(kind, _check_name(name), _ns(kind, namespace))}


@router.get("/k8s/{kind}/{namespace}/{name}/relations")
def resource_relations(kind: str, namespace: str, name: str, _: Session = Depends(require(Perm.CLUSTER_READ)),
                       ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    return ctx.k8s.relations(kind, _check_name(name), _ns(kind, namespace))


@router.get("/k8s/{kind}/{namespace}/{name}/diagnose")
def resource_diagnose(kind: str, namespace: str, name: str, _: Session = Depends(require(Perm.CLUSTER_READ)),
                      ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    return {"items": ctx.k8s.diagnose(kind, _check_name(name), _ns(kind, namespace))}


@router.get("/k8s/{kind}/{namespace}/{name}/metrics")
def resource_metrics(kind: str, namespace: str, name: str, _: Session = Depends(require(Perm.MONITORING_READ)),
                     ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    from ..k8s.quantity import bytes_, cpu_cores
    from ..k8s.summarize import top_owner

    ns = _ns(kind, namespace)
    _check_name(name)
    if kind == "nodes":
        m = ctx.k8s.node_metrics()
        if m is None:
            return {"available": False, "source": "metrics-server"}
        row = next((x for x in m if x["metadata"]["name"] == name), None)
        return {"available": True, "source": "metrics-server", "node": row and {
            "cpu": cpu_cores(row["usage"].get("cpu")), "memory": bytes_(row["usage"].get("memory"))}}
    pm = ctx.k8s.pod_metrics(ns)
    if pm is None:
        return {"available": False, "source": "metrics-server"}
    pods = {p["metadata"]["name"]: p for p in ctx.k8s.list_raw(KINDS["pods"], ns)}
    rows = []
    for m in pm:
        pod = pods.get(m["metadata"]["name"])
        if pod is None:
            continue
        owner = top_owner(pod) or {}
        if kind == "pods" and m["metadata"]["name"] != name:
            continue
        if kind != "pods" and not (owner.get("name") == name and get_kind(kind).kind == owner.get("kind")):
            continue
        for c in m.get("containers") or []:
            spec = next((x for x in pod["spec"]["containers"] if x["name"] == c["name"]), {})
            res = spec.get("resources") or {}
            rows.append({"pod": m["metadata"]["name"], "container": c["name"],
                         "cpu": cpu_cores(c["usage"].get("cpu")), "memory": bytes_(c["usage"].get("memory")),
                         "cpuLimit": cpu_cores((res.get("limits") or {}).get("cpu")),
                         "memoryLimit": bytes_((res.get("limits") or {}).get("memory")),
                         "cpuRequest": cpu_cores((res.get("requests") or {}).get("cpu")),
                         "memoryRequest": bytes_((res.get("requests") or {}).get("memory"))})  # fmt: skip
    return {"available": True, "source": "metrics-server", "containers": rows}


# ---------------------------------------------------------------- logs
def _container_for(ctx: AppContext, name: str, ns: str, container: str | None) -> str | None:
    pod = ctx.k8s.get_raw(KINDS["pods"], name, ns)
    names = [c["name"] for c in (pod.get("spec") or {}).get("containers") or []]
    names += [c["name"] for c in (pod.get("spec") or {}).get("initContainers") or []]
    if container and container not in names:
        raise ValidationFailed(f"container '{container}' not found in pod", params={"field": "container",
                                                                                   "available": names})  # fmt: skip
    return container or (names[0] if names else None)


@router.get("/k8s/pods/{namespace}/{name}/logs")
def pod_logs(namespace: str, name: str, request: Request, container: str | None = Query(None, max_length=253),
             tail: int = Query(500, ge=1, le=50000), since_seconds: int | None = Query(None, ge=1, le=30 * 86400),
             timestamps: bool = True, previous: bool = False, download: bool = False,
             session: Session = Depends(require(Perm.LOGS_READ)), ctx: AppContext = Depends(get_ctx),
             audit: Audited = Depends(audited)) -> Any:  # fmt: skip
    validate_name(namespace, "namespace")
    _check_name(name)
    tail = min(tail, ctx.settings.logs.max_tail_lines)
    c = _container_for(ctx, name, namespace, container)
    text = ctx.k8s.pod_logs(name, namespace, container=c, tail_lines=tail, since_seconds=since_seconds,
                            timestamps=timestamps, previous=previous, limit_bytes=10 * 1024 * 1024)  # fmt: skip
    if download:
        audit("logs.download", kind="Pod", name=name, namespace=namespace, detail={"container": c, "tail": tail})
        fname = f"{namespace}_{name}_{c}{'_previous' if previous else ''}.log"
        return PlainTextResponse(text, headers={"Content-Disposition": f'attachment; filename="{fname}"'})
    lines = text.splitlines()
    return {"container": c, "lines": lines, "count": len(lines), "truncated": len(lines) >= tail, "tail": tail}


@router.get("/k8s/pods/{namespace}/{name}/logs/stream")
async def pod_logs_stream(namespace: str, name: str, request: Request,
                          container: str | None = Query(None, max_length=253), tail: int = Query(100, ge=0, le=5000),
                          session: Session = Depends(require(Perm.LOGS_READ)),
                          ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:  # fmt: skip
    validate_name(namespace, "namespace")
    _check_name(name)
    if ctx.log_streams.locked():
        raise RateLimited("too many live log streams are open", params={"limit": ctx.settings.logs.max_concurrent_streams})
    c = await asyncio.to_thread(_container_for, ctx, name, namespace, container)
    await ctx.log_streams.acquire()
    try:
        stream = await asyncio.to_thread(ctx.k8s.stream_pod_logs, name, namespace, container=c, tail_lines=tail)
    except BaseException:
        ctx.log_streams.release()
        raise
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=2000)
    stop = threading.Event()

    def put(item: tuple[str, Any]) -> bool:
        fut = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
        try:
            fut.result(timeout=30)
            return True
        except Exception:
            fut.cancel()
            return False

    def pump() -> None:
        try:
            for line in stream:
                if stop.is_set() or not put(("line", line)):
                    return
            put(("end", None))
        except AppError as exc:
            put(("error", {"code": exc.code, "message": exc.message}))
        except Exception as exc:
            put(("error", {"code": "stream_error", "message": str(exc)}))

    threading.Thread(target=pump, name=f"logs-{namespace}-{name}", daemon=True).start()
    max_lines = ctx.settings.logs.stream_max_lines
    deadline = time.monotonic() + ctx.settings.logs.stream_max_seconds

    async def gen():  # type: ignore[no-untyped-def]
        sent = 0
        try:
            yield f"event: open\ndata: {json.dumps({'container': c})}\n\n"
            while True:
                if await request.is_disconnected():
                    return
                if time.monotonic() > deadline:
                    yield f"event: limit\ndata: {json.dumps({'reason': 'duration'})}\n\n"
                    return
                try:
                    kind, val = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if kind == "line":
                    batch = [val]
                    while not queue.empty() and len(batch) < 200:
                        k2, v2 = queue.get_nowait()
                        if k2 != "line":
                            await queue.put((k2, v2))
                            break
                        batch.append(v2)
                    sent += len(batch)
                    yield f"data: {json.dumps(batch)}\n\n"
                    if sent >= max_lines:
                        yield f"event: limit\ndata: {json.dumps({'reason': 'lines', 'lines': sent})}\n\n"
                        return
                elif kind == "end":
                    yield "event: end\ndata: {}\n\n"
                    return
                else:
                    yield f"event: error\ndata: {json.dumps(val)}\n\n"
                    return
        finally:
            stop.set()
            await asyncio.to_thread(stream.close)
            ctx.log_streams.release()

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # fmt: skip


# ---------------------------------------------------------------- delete
@router.delete("/k8s/{kind}/{namespace}/{name}")
def delete_resource(kind: str, namespace: str, name: str, confirm: str | None = Query(None, max_length=253),
                    session: Session = Depends(current_session), ctx: AppContext = Depends(get_ctx),
                    audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    info = get_kind(kind)
    ns = _ns(kind, namespace)
    _check_name(name)
    if "delete" not in info.actions:
        raise NotSupported(f"{info.kind} cannot be deleted from this application", params={"kind": info.kind})
    perm = Perm.PODS_DELETE if kind == "pods" else Perm.RESOURCES_DELETE
    if not has_perm(session.user.role, perm):
        audit("resource.delete", result="denied", kind=info.kind, name=name, namespace=ns)
        raise Forbidden("your role does not allow this operation", params={"permission": perm.value})
    if kind != "pods":
        risk = "high" if kind in HIGH_RISK_DELETE else "medium"
        _confirm(confirm, name, what=f"delete {info.kind} {name}", params={"kind": info.kind, "risk": risk})
    elif kind == "pods":
        pod = ctx.k8s.get_raw(info, name, ns)
        if controller_of(pod) is None:
            _confirm(confirm, name, what="delete an unmanaged pod (it will not be recreated)",
                     params={"kind": "Pod", "risk": "high", "reason": "unmanaged"})  # fmt: skip
    try:
        ctx.k8s.delete(kind, name, ns)
    except AppError as exc:
        audit("resource.delete", result="failure", kind=info.kind, name=name, namespace=ns, detail={"error": exc.code})
        raise
    audit("resource.delete", kind=info.kind, name=name, namespace=ns)
    return {"ok": True}


# ---------------------------------------------------------------- workload operations
class ScaleBody(BaseModel):
    replicas: int = Field(ge=0, le=500)
    confirm: str | None = Field(None, max_length=253)


@router.post("/k8s/{kind}/{namespace}/{name}/scale")
def scale(kind: str, namespace: str, name: str, body: ScaleBody, _: Session = Depends(require(Perm.WORKLOADS_SCALE)),
          ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ns = _ns(kind, namespace)
    _check_name(name)
    if kind not in ("deployments", "statefulsets"):
        raise NotSupported("only Deployments and StatefulSets can be scaled", params={"kind": kind})
    current = ctx.k8s.get_raw(get_kind(kind), name, ns)
    before = (current.get("spec") or {}).get("replicas", 1)
    if body.replicas == 0:
        _confirm(body.confirm, name, what="scale to zero (the application stops)", params={"risk": "high"})
    try:
        res = ctx.k8s.scale(kind, name, ns or "", body.replicas)
    except AppError as exc:
        audit("workload.scale", result="failure", kind=get_kind(kind).kind, name=name, namespace=ns,
              detail={"from": before, "to": body.replicas, "error": exc.code})  # fmt: skip
        raise
    audit("workload.scale", kind=get_kind(kind).kind, name=name, namespace=ns, detail={"from": before, "to": body.replicas})
    return {"summary": res}


class ConfirmBody(BaseModel):
    confirm: str | None = Field(None, max_length=253)


@router.post("/k8s/{kind}/{namespace}/{name}/restart")
def restart(kind: str, namespace: str, name: str, body: ConfirmBody | None = None,
            _: Session = Depends(require(Perm.WORKLOADS_RESTART)), ctx: AppContext = Depends(get_ctx),
            audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    ns = _ns(kind, namespace)
    _check_name(name)
    info = get_kind(kind)
    try:
        if kind == "pods":
            pod = ctx.k8s.get_raw(info, name, ns)
            if controller_of(pod) is None:
                _confirm((body or ConfirmBody()).confirm, name,
                         what="restart an unmanaged pod: it will be deleted and NOT recreated",
                         params={"risk": "high", "reason": "unmanaged"})  # fmt: skip
            ctx.k8s.delete("pods", name, ns)
            res: dict[str, Any] = {"deleted": name}
        else:
            res = {"summary": ctx.k8s.restart(kind, name, ns or "")}
    except ConfirmationRequired:
        raise
    except AppError as exc:
        audit("workload.restart", result="failure", kind=info.kind, name=name, namespace=ns, detail={"error": exc.code})
        raise
    audit("workload.restart", kind=info.kind, name=name, namespace=ns)
    return res


@router.post("/k8s/deployments/{namespace}/{name}/pause")
def pause(namespace: str, name: str, _: Session = Depends(require(Perm.WORKLOADS_ROLLOUT)),
          ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.k8s.set_paused(_check_name(name), validate_name(namespace, "namespace"), True)
    audit("rollout.pause", kind="Deployment", name=name, namespace=namespace)
    return {"summary": res}


@router.post("/k8s/deployments/{namespace}/{name}/resume")
def resume(namespace: str, name: str, _: Session = Depends(require(Perm.WORKLOADS_ROLLOUT)),
           ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.k8s.set_paused(_check_name(name), validate_name(namespace, "namespace"), False)
    audit("rollout.resume", kind="Deployment", name=name, namespace=namespace)
    return {"summary": res}


@router.get("/k8s/deployments/{namespace}/{name}/rollout")
def rollout(namespace: str, name: str, _: Session = Depends(require(Perm.CLUSTER_READ)),
            ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    data = ctx.k8s.rollout(_check_name(name), validate_name(namespace, "namespace"))
    for h in data["history"]:
        h["templateYaml"] = yaml.safe_dump(h.pop("template"), sort_keys=False)
    return data


class RollbackBody(BaseModel):
    revision: int | None = Field(None, ge=1)


@router.post("/k8s/deployments/{namespace}/{name}/rollback")
def rollback(namespace: str, name: str, body: RollbackBody, _: Session = Depends(require(Perm.WORKLOADS_ROLLOUT)),
             ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    try:
        res = ctx.k8s.rollback(_check_name(name), validate_name(namespace, "namespace"), body.revision)
    except AppError as exc:
        audit("rollout.rollback", result="failure", kind="Deployment", name=name, namespace=namespace,
              detail={"revision": body.revision, "error": exc.code})  # fmt: skip
        raise
    audit("rollout.rollback", kind="Deployment", name=name, namespace=namespace, detail={"toRevision": res["revision"]})
    return res


class SuspendBody(BaseModel):
    suspend: bool


@router.post("/k8s/cronjobs/{namespace}/{name}/suspend")
def suspend_cronjob(namespace: str, name: str, body: SuspendBody, _: Session = Depends(require(Perm.WORKLOADS_ROLLOUT)),
                    ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.k8s.set_cronjob_suspended(_check_name(name), validate_name(namespace, "namespace"), body.suspend)
    audit("cronjob.suspend" if body.suspend else "cronjob.resume", kind="CronJob", name=name, namespace=namespace)
    return {"summary": res}


@router.post("/k8s/cronjobs/{namespace}/{name}/trigger")
def trigger_cronjob(namespace: str, name: str, _: Session = Depends(require(Perm.WORKLOADS_DEPLOY)),
                    ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.k8s.trigger_cronjob(_check_name(name), validate_name(namespace, "namespace"))
    audit("cronjob.trigger", kind="CronJob", name=name, namespace=namespace, detail={"job": res["name"]})
    return {"summary": res}


# ---------------------------------------------------------------- nodes
@router.post("/k8s/nodes/_/{name}/cordon")
def cordon(name: str, _: Session = Depends(require(Perm.NODES_MAINTAIN)), ctx: AppContext = Depends(get_ctx),
           audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.k8s.set_cordon(_check_name(name), True)
    audit("node.cordon", kind="Node", name=name)
    return {"summary": res}


@router.post("/k8s/nodes/_/{name}/uncordon")
def uncordon(name: str, _: Session = Depends(require(Perm.NODES_MAINTAIN)), ctx: AppContext = Depends(get_ctx),
             audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    res = ctx.k8s.set_cordon(_check_name(name), False)
    audit("node.uncordon", kind="Node", name=name)
    return {"summary": res}


@router.get("/k8s/nodes/_/{name}/drain-plan")
def drain_plan(name: str, _: Session = Depends(require(Perm.NODES_MAINTAIN)),
               ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    return ctx.k8s.drain_plan(_check_name(name))


class DrainBody(BaseModel):
    confirm: str | None = Field(None, max_length=253)
    force_unmanaged: bool = False
    delete_emptydir: bool = False
    timeout_seconds: int = Field(600, ge=30, le=3600)


@router.post("/k8s/nodes/_/{name}/drain")
def drain(name: str, body: DrainBody, request: Request, session: Session = Depends(require(Perm.NODES_MAINTAIN)),
          ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    _check_name(name)
    _confirm(body.confirm, name, what=f"drain node {name}", params={"risk": "high"})
    plan = ctx.k8s.drain_plan(name)
    if any(p["action"] == "blocked" and not ((p["reason"] == "unmanaged" and body.force_unmanaged) or
                                             (p["reason"] == "emptydir" and body.delete_emptydir))
           for p in plan["pods"]):  # fmt: skip
        raise BadRequest("some pods cannot be evicted safely", params={"rule": "drain_blocked", "plan": plan["pods"]})
    audit("node.drain.start", kind="Node", name=name, detail=body.model_dump(exclude={"confirm"}))

    def run(op):  # type: ignore[no-untyped-def]
        return ctx.k8s.drain(name, force_unmanaged=body.force_unmanaged, delete_emptydir=body.delete_emptydir,
                             timeout_seconds=body.timeout_seconds, progress=op.progress, cancelled=op.cancelled)  # fmt: skip

    actx = audit_ctx(request, session)

    def done(op):  # type: ignore[no-untyped-def]
        ok = op.status == "succeeded" and not (op.result or {}).get("timedOut")
        ctx.audit.record(actx, "node.drain.finish", result="success" if ok else "failure", kind="Node", name=name,
                         detail={"status": op.status, "result": op.result, "error": op.error})  # fmt: skip

    op = ctx.operations.start("drain", name, session.user.username, run, done)
    return {"operation": op.public()}


# ---------------------------------------------------------------- YAML validate / apply
class YamlBody(BaseModel):
    yaml: str = Field(max_length=MAX_YAML)
    namespace: str | None = Field(None, max_length=63)
    dry_run: bool = False
    force: bool = False


def _parse_yaml(text: str, default_ns: str | None) -> list[dict[str, Any]]:
    try:
        docs = [d for d in yaml.safe_load_all(text) if d is not None]
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark
        raise ValidationFailed("YAML syntax error", params={
            "errors": [{"line": (mark.line + 1) if mark else None, "column": (mark.column + 1) if mark else None,
                        "message": str(exc.problem or exc)}]}) from exc  # fmt: skip
    except yaml.YAMLError as exc:
        raise ValidationFailed("YAML syntax error", params={"errors": [{"message": str(exc)}]}) from exc
    if not docs:
        raise ValidationFailed("the document is empty", params={"errors": [{"message": "empty"}]})
    if len(docs) > MAX_DOCS:
        raise ValidationFailed(f"too many documents (max {MAX_DOCS})")
    out = []
    for i, d in enumerate(docs):
        doc = validate_manifest_shape(d, i)
        info = kind_for_manifest(doc["apiVersion"], doc["kind"])
        if info.namespaced and not doc["metadata"].get("namespace"):
            doc["metadata"]["namespace"] = default_ns or "default"
        out.append(doc)
    return out


def _required_perm(doc: dict[str, Any]) -> Perm:
    info = kind_for_manifest(doc["apiVersion"], doc["kind"])
    return Perm.WORKLOADS_DEPLOY if info.workload else Perm.RESOURCES_APPLY


def _apply_docs(ctx: AppContext, session: Session, docs: list[dict[str, Any]], *, dry_run: bool, force: bool,
                audit: Audited, action: str) -> list[dict[str, Any]]:  # fmt: skip
    from ..k8s.service import sanitize
    from ..k8s.summarize import summarize

    for doc in docs:
        perm = _required_perm(doc)
        if not has_perm(session.user.role, perm):
            raise Forbidden(f"your role cannot create or change {doc['kind']} resources",
                            params={"permission": perm.value, "kind": doc["kind"]})  # fmt: skip
        if doc["kind"] == "Secret" and not has_perm(session.user.role, Perm.SECRETS_READ_VALUES):
            raise Forbidden("your role cannot write secrets", params={"permission": Perm.SECRETS_READ_VALUES.value})
    results = []
    for doc in docs:
        meta = doc["metadata"]
        info = kind_for_manifest(doc["apiVersion"], doc["kind"])
        exists = True
        try:
            ctx.k8s.get_raw(info, meta["name"], meta.get("namespace"))
        except K8sNotFound:
            exists = False
        try:
            obj = ctx.k8s.apply(doc, dry_run=dry_run, force=force)
        except AppError as exc:
            results.append({"kind": doc["kind"], "name": meta["name"], "namespace": meta.get("namespace"),
                            "ok": False, "existed": exists,
                            "error": {"code": exc.code, "message": exc.message, "params": exc.params}})  # fmt: skip
            if not dry_run:
                audit(action, result="failure", kind=doc["kind"], name=meta["name"], namespace=meta.get("namespace"),
                      detail={"error": exc.code, "message": exc.message})  # fmt: skip
            continue
        results.append({"kind": doc["kind"], "name": meta["name"], "namespace": meta.get("namespace"), "ok": True,
                        "existed": exists, "summary": summarize(obj),
                        "result": yaml.safe_dump(sanitize(obj), sort_keys=False)})  # fmt: skip
        if not dry_run:
            audit(action, kind=doc["kind"], name=meta["name"], namespace=meta.get("namespace"),
                  detail={"operation": "update" if exists else "create", "force": force})  # fmt: skip
    return results


@router.post("/k8s/validate")
def validate_yaml(body: YamlBody, session: Session = Depends(require(Perm.CLUSTER_READ)),
                  ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    try:
        docs = _parse_yaml(body.yaml, body.namespace)
    except ValidationFailed as exc:
        return {"valid": False, "errors": exc.params.get("errors") or [{"message": exc.message}], "documents": []}
    except AppError as exc:
        return {"valid": False, "errors": [{"message": exc.message, "code": exc.code}], "documents": []}
    can_write = all(has_perm(session.user.role, _required_perm(d)) for d in docs)
    if not can_write:
        return {"valid": True, "serverChecked": False, "errors": [], "documents": [
            {"kind": d["kind"], "name": d["metadata"]["name"], "namespace": d["metadata"].get("namespace")} for d in docs]}
    results = _apply_docs(ctx, session, docs, dry_run=True, force=False, audit=audit, action="resource.validate")
    errors = [{"document": i + 1, "message": r["error"]["message"], "causes": r["error"]["params"].get("causes")}
              for i, r in enumerate(results) if not r["ok"]]  # fmt: skip
    return {"valid": not errors, "serverChecked": True, "errors": errors, "documents": results}


@router.post("/k8s/apply")
def apply_yaml(body: YamlBody, session: Session = Depends(current_session), ctx: AppContext = Depends(get_ctx),
               audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    if body.namespace:
        validate_name(body.namespace, "namespace")
    if body.force and not has_perm(session.user.role, Perm.RESOURCES_APPLY):
        raise Forbidden("only administrators can force a conflicting apply", params={"permission": "resources.apply"})
    docs = _parse_yaml(body.yaml, body.namespace)
    results = _apply_docs(ctx, session, docs, dry_run=body.dry_run, force=body.force, audit=audit,
                          action="resource.apply")  # fmt: skip
    return {"ok": all(r["ok"] for r in results), "dryRun": body.dry_run, "results": results}


# ---------------------------------------------------------------- guided deployment
@router.post("/deploy/preview")
def deploy_preview(spec: manifests.DeploySpec, session: Session = Depends(require(Perm.WORKLOADS_DEPLOY)),
                   ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    docs = manifests.generate(spec)
    risks = manifests.risks(spec)
    blocking: list[dict[str, Any]] = []
    if not spec.create_namespace:
        try:
            ctx.k8s.get_raw(KINDS["namespaces"], spec.namespace, None)
        except K8sNotFound:
            blocking.append({"code": "namespace_missing", "params": {"namespace": spec.namespace}})
    elif not has_perm(session.user.role, Perm.RESOURCES_APPLY):
        blocking.append({"code": "namespace_create_forbidden", "params": {}})
    existing = []
    for d in docs:
        info = kind_for_manifest(d["apiVersion"], d["kind"])
        try:
            ctx.k8s.get_raw(info, d["metadata"]["name"], d["metadata"].get("namespace"))
            existing.append({"kind": d["kind"], "name": d["metadata"]["name"]})
        except K8sNotFound:
            pass
    if existing:
        risks.append({"level": "high", "code": "overwrite_existing", "params": {"resources": existing}})
    dry: list[dict[str, Any]] = []
    if not blocking:
        dry = _apply_docs(ctx, session, [json.loads(json.dumps(d)) for d in docs], dry_run=True, force=False,
                          audit=audit, action="deploy.validate")  # fmt: skip
    return {"manifests": docs, "yaml": manifests.to_yaml(docs), "risks": risks, "blocking": blocking,
            "dryRun": [{k: v for k, v in r.items() if k != "result"} for r in dry],
            "valid": not blocking and all(r["ok"] for r in dry)}  # fmt: skip


@router.post("/deploy")
def deploy(spec: manifests.DeploySpec, session: Session = Depends(require(Perm.WORKLOADS_DEPLOY)),
           ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    docs = manifests.generate(spec)
    if spec.create_namespace and not has_perm(session.user.role, Perm.RESOURCES_APPLY):
        raise Forbidden("only administrators can create namespaces", params={"permission": "resources.apply"})
    results = _apply_docs(ctx, session, docs, dry_run=False, force=False, audit=audit, action="deploy.apply")
    ok = all(r["ok"] for r in results)
    audit("deploy.wizard", result="success" if ok else "failure", kind="Deployment", name=spec.name,
          namespace=spec.namespace, detail={"image": f"{spec.image}:{spec.tag}", "replicas": spec.replicas})  # fmt: skip
    return {"ok": ok, "results": [{k: v for k, v in r.items() if k != "result"} for r in results]}


# ---------------------------------------------------------------- image onboarding
class InspectBody(BaseModel):
    image: str = Field(min_length=1, max_length=512)
    username: str | None = Field(None, max_length=256)
    password: str | None = Field(None, max_length=4096)


@router.post("/images/inspect")
def inspect_image(body: InspectBody, _: Session = Depends(require(Perm.WORKLOADS_DEPLOY)),
                  ctx: AppContext = Depends(get_ctx), audit: Audited = Depends(audited)) -> dict[str, Any]:  # fmt: skip
    if ctx.demo:
        res = image_tools.demo_inspect(body.image.strip())
    else:
        res = image_tools.RegistryInspector().inspect(body.image.strip(), username=body.username,
                                                      password=body.password)  # fmt: skip
    audit("image.inspect", kind="Image", name=body.image[:250],
          detail={"checks": {c["id"]: c["status"] for c in res["checks"]}, "withCredentials": bool(body.username)})  # fmt: skip
    return res


# ---------------------------------------------------------------- HA analysis
@router.get("/cluster/ha")
def high_availability(namespace: str | None = Query(None, max_length=63),
                      _: Session = Depends(require(Perm.CLUSTER_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    from ..k8s.summarize import node_ready, summarize, top_owner

    if namespace:
        validate_name(namespace, "namespace")
    data, partial = ctx.k8s.snapshot(namespace, kinds=["deployments", "statefulsets", "pods", "nodes"])
    try:
        pdbs = ctx.k8s.list_raw(KINDS["poddisruptionbudgets"], namespace)
    except AppError:
        pdbs = []
    pods_by_owner: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for p in data["pods"]:
        o = top_owner(p)
        if o:
            pods_by_owner.setdefault((p["metadata"].get("namespace", ""), o["kind"], o["name"]), []).append(p)
    rows = []
    for kind_name, lst in (("Deployment", data["deployments"]), ("StatefulSet", data["statefulsets"])):
        for w in lst:
            meta, spec = w["metadata"], w.get("spec") or {}
            s = summarize(w)
            pods = pods_by_owner.get((meta.get("namespace", ""), kind_name, meta["name"]), [])
            nodes = {(p.get("spec") or {}).get("nodeName") for p in pods if (p.get("spec") or {}).get("nodeName")}
            tmpl_labels = ((spec.get("template") or {}).get("metadata") or {}).get("labels") or {}
            pdb = next((d["metadata"]["name"] for d in pdbs if d["metadata"].get("namespace") == meta.get("namespace")
                        and all(tmpl_labels.get(k) == v for k, v in ((d.get("spec") or {}).get("selector") or {})
                                .get("matchLabels", {}).items())), None)  # fmt: skip
            containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
            flags = []
            replicas = spec.get("replicas", 1)
            if replicas <= 1:
                flags.append("single_replica")
            if replicas > 1 and len(nodes) == 1:
                flags.append("same_node")
            if replicas > 1 and not pdb:
                flags.append("no_pdb")
            if any(not c.get("readinessProbe") for c in containers):
                flags.append("no_readiness")
            if any(not c.get("livenessProbe") for c in containers):
                flags.append("no_liveness")
            if any(not (c.get("resources") or {}).get("requests") for c in containers):
                flags.append("no_requests")
            if any(not ((c.get("resources") or {}).get("limits") or {}).get("memory") for c in containers):
                flags.append("no_memory_limit")
            restarts = sum(cs.get("restartCount", 0) for p in pods for cs in (p.get("status") or {}).get("containerStatuses") or [])
            rows.append({"kind": kind_name, "name": meta["name"], "namespace": meta.get("namespace"),
                         "replicas": replicas, "ready": s.get("readyReplicas", 0), "health": s["health"],
                         "nodes": sorted(n for n in nodes if n), "pdb": pdb, "strategy": (spec.get("strategy") or {}).get("type"),
                         "restarts": restarts, "flags": flags})  # fmt: skip
    nodes = [summarize(n) for n in data["nodes"]]
    return {"workloads": rows, "nodes": [{k: n.get(k) for k in ("name", "health", "ready", "pressures", "unschedulable",
                                                                 "roles")} for n in nodes],
            "readyNodes": sum(1 for n in data["nodes"] if node_ready(n)), "partial": partial}  # fmt: skip
