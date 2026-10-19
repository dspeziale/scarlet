"""Monitoring: metrics-server usage, Prometheus (optional), storage."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from ..context import AppContext
from ..errors import MetricsUnavailable
from ..k8s.naming import validate_name
from ..monitoring import PROM_QUERIES, RANGES, node_usage, pod_usage, storage_overview
from ..security.rbac import Perm
from ..security.users import Session
from .deps import get_ctx, require

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/sources")
def sources(_: Session = Depends(require(Perm.MONITORING_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    ms = ctx.k8s.node_metrics() is not None if ctx.k8s.info().get("connected") else False
    prom: dict[str, Any] = {"configured": ctx.prometheus.configured, "ok": False}
    if ctx.prometheus.configured:
        try:
            prom.update(ctx.prometheus.ping())
        except MetricsUnavailable as exc:
            prom["error"] = exc.message
    return {"metricsServer": ms, "prometheus": prom, "queries": sorted(PROM_QUERIES), "ranges": list(RANGES)}


@router.get("/nodes")
def nodes(_: Session = Depends(require(Perm.MONITORING_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return node_usage(ctx.k8s)


@router.get("/pods")
def pods(namespace: str | None = Query(None, max_length=63), sort: Literal["cpu", "memory"] = "cpu",
         limit: int = Query(50, ge=1, le=500), _: Session = Depends(require(Perm.MONITORING_READ)),
         ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    if namespace:
        validate_name(namespace, "namespace")
    return pod_usage(ctx.k8s, namespace, sort, limit)


@router.get("/storage")
def storage(_: Session = Depends(require(Perm.MONITORING_READ)), ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    return storage_overview(ctx.k8s, ctx.prometheus)


@router.get("/prometheus/{name}")
def prometheus(name: str, range: str | None = Query(None), _: Session = Depends(require(Perm.MONITORING_READ)),
               ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:  # fmt: skip
    if range:
        return {"name": name, "range": range, "series": ctx.prometheus.query_range(name, range)}
    return {"name": name, "result": ctx.prometheus.query(name)}
