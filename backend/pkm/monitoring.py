"""Metrics: metrics-server (current CPU/RAM) and, when configured, Prometheus (history, network, filesystem).

Never invents data: every response says which source was used and whether it is available.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .config import MonitoringConfig
from .errors import BadRequest, MetricsUnavailable
from .k8s.kinds import KINDS
from .k8s.quantity import bytes_, cpu_cores
from .k8s.service import KubernetesService
from .k8s.summarize import node_ready

# Named PromQL queries; the UI can only ask for these (no arbitrary PromQL from the browser).
PROM_QUERIES: dict[str, str] = {
    "cluster_cpu": 'sum(rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m]))',
    "cluster_memory": 'sum(container_memory_working_set_bytes{container!="",container!="POD"})',
    "cluster_network_rx": 'sum(rate(container_network_receive_bytes_total[5m]))',
    "cluster_network_tx": 'sum(rate(container_network_transmit_bytes_total[5m]))',
    "node_cpu": 'sum by (instance) (rate(node_cpu_seconds_total{mode!="idle"}[5m]))',
    "node_memory": 'sum by (instance) (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes)',
    "node_fs_used_ratio": '1 - sum by (instance) (node_filesystem_avail_bytes{fstype!~"tmpfs|overlay|squashfs"})'
                          ' / sum by (instance) (node_filesystem_size_bytes{fstype!~"tmpfs|overlay|squashfs"})',
    "namespace_cpu": 'sum by (namespace) (rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m]))',
    "namespace_memory": 'sum by (namespace) (container_memory_working_set_bytes{container!="",container!="POD"})',
    "namespace_network_rx": 'sum by (namespace) (rate(container_network_receive_bytes_total[5m]))',
    "pvc_used_ratio": 'max by (namespace, persistentvolumeclaim) (kubelet_volume_stats_used_bytes'
                      ' / kubelet_volume_stats_capacity_bytes)',
    "restarts_1h": 'sum by (namespace, pod) (increase(kube_pod_container_status_restarts_total[1h])) > 0',
}  # fmt: skip
RANGES = {"1h": (3600, 60), "6h": (6 * 3600, 300), "24h": (86400, 900), "7d": (7 * 86400, 3600)}


class Prometheus:
    def __init__(self, cfg: MonitoringConfig) -> None:
        self.cfg = cfg

    @property
    def configured(self) -> bool:
        return bool(self.cfg.prometheus_url)

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        if not self.cfg.prometheus_url:
            raise MetricsUnavailable("Prometheus is not configured", params={"source": "prometheus",
                                                                             "reason": "not_configured"})  # fmt: skip
        headers = {"Authorization": f"Bearer {self.cfg.prometheus_token}"} if self.cfg.prometheus_token else {}
        try:
            resp = httpx.get(self.cfg.prometheus_url + path, params=params, headers=headers,
                             timeout=self.cfg.prometheus_timeout, verify=self.cfg.prometheus_verify_tls)  # fmt: skip
        except httpx.HTTPError as exc:
            raise MetricsUnavailable("Prometheus is not reachable", details=str(exc),
                                     params={"source": "prometheus", "reason": "unreachable"}) from exc  # fmt: skip
        if resp.status_code != 200:
            raise MetricsUnavailable(f"Prometheus answered {resp.status_code}", details=resp.text[:500],
                                     params={"source": "prometheus", "reason": "error"})  # fmt: skip
        data = resp.json()
        if data.get("status") != "success":
            raise MetricsUnavailable("Prometheus query failed", details=str(data.get("error")),
                                     params={"source": "prometheus", "reason": "query"})  # fmt: skip
        return data["data"]

    def ping(self) -> dict[str, Any]:
        start = time.monotonic()
        data = self._get("/api/v1/query", {"query": "up"})
        return {"ok": True, "targets": len(data.get("result") or []), "latencyMs": int((time.monotonic() - start) * 1000)}

    def query(self, name: str) -> list[dict[str, Any]]:
        q = PROM_QUERIES.get(name)
        if q is None:
            raise BadRequest(f"unknown query '{name}'", params={"field": "query"})
        data = self._get("/api/v1/query", {"query": q})
        return [{"labels": r.get("metric") or {}, "value": float(r["value"][1])} for r in data.get("result") or []]

    def query_range(self, name: str, rng: str) -> list[dict[str, Any]]:
        q = PROM_QUERIES.get(name)
        if q is None:
            raise BadRequest(f"unknown query '{name}'", params={"field": "query"})
        if rng not in RANGES:
            raise BadRequest("invalid range", params={"field": "range", "allowed": list(RANGES)})
        span, step = RANGES[rng]
        end = time.time()
        data = self._get("/api/v1/query_range", {"query": q, "start": end - span, "end": end, "step": step})
        return [{"labels": r.get("metric") or {}, "values": [[float(t), float(v)] for t, v in r.get("values") or []]}
                for r in data.get("result") or []]  # fmt: skip


def node_usage(k8s: KubernetesService) -> dict[str, Any]:
    nodes = k8s.list_raw(KINDS["nodes"])
    metrics = k8s.node_metrics()
    by_name = {m["metadata"]["name"]: m for m in metrics or []}
    pods = k8s.list_raw(KINDS["pods"])
    requests: dict[str, dict[str, float]] = {}
    for p in pods:
        node = (p.get("spec") or {}).get("nodeName")
        if not node or (p.get("status") or {}).get("phase") not in ("Running", "Pending"):
            continue
        r = requests.setdefault(node, {"cpu": 0.0, "memory": 0.0, "cpuLimit": 0.0, "memoryLimit": 0.0, "pods": 0})
        r["pods"] += 1
        for c in (p.get("spec") or {}).get("containers") or []:
            res = c.get("resources") or {}
            r["cpu"] += cpu_cores((res.get("requests") or {}).get("cpu")) or 0
            r["memory"] += bytes_((res.get("requests") or {}).get("memory")) or 0
            r["cpuLimit"] += cpu_cores((res.get("limits") or {}).get("cpu")) or 0
            r["memoryLimit"] += bytes_((res.get("limits") or {}).get("memory")) or 0
    rows = []
    for n in nodes:
        name = n["metadata"]["name"]
        alloc = (n.get("status") or {}).get("allocatable") or {}
        cap = (n.get("status") or {}).get("capacity") or {}
        m = by_name.get(name)
        rows.append({
            "name": name, "ready": node_ready(n), "unschedulable": bool((n.get("spec") or {}).get("unschedulable")),
            "allocatableCpu": cpu_cores(alloc.get("cpu")), "allocatableMemory": bytes_(alloc.get("memory")),
            "allocatablePods": int(alloc.get("pods") or 0), "capacityEphemeral": bytes_(cap.get("ephemeral-storage")),
            "allocatableEphemeral": bytes_(alloc.get("ephemeral-storage")),
            "usageCpu": cpu_cores((m.get("usage") or {}).get("cpu")) if m else None,
            "usageMemory": bytes_((m.get("usage") or {}).get("memory")) if m else None,
            "requests": requests.get(name, {"cpu": 0.0, "memory": 0.0, "cpuLimit": 0.0, "memoryLimit": 0.0, "pods": 0}),
            "pressures": [c["type"] for c in (n.get("status") or {}).get("conditions") or []
                          if c.get("type") != "Ready" and c.get("status") == "True"],
        })  # fmt: skip
    return {"metricsServer": metrics is not None, "nodes": rows}


def pod_usage(k8s: KubernetesService, namespace: str | None, sort: str = "cpu", limit: int = 50) -> dict[str, Any]:
    metrics = k8s.pod_metrics(namespace)
    if metrics is None:
        return {"metricsServer": False, "pods": []}
    pods = {(p["metadata"].get("namespace"), p["metadata"]["name"]): p
            for p in k8s.list_raw(KINDS["pods"], namespace)}  # fmt: skip
    rows = []
    for m in metrics:
        key = (m["metadata"].get("namespace"), m["metadata"]["name"])
        pod = pods.get(key)
        cpu = sum(cpu_cores((c.get("usage") or {}).get("cpu")) or 0 for c in m.get("containers") or [])
        mem = sum(bytes_((c.get("usage") or {}).get("memory")) or 0 for c in m.get("containers") or [])
        lim_cpu = lim_mem = req_cpu = req_mem = 0.0
        for c in ((pod or {}).get("spec") or {}).get("containers") or []:
            res = c.get("resources") or {}
            lim_cpu += cpu_cores((res.get("limits") or {}).get("cpu")) or 0
            lim_mem += bytes_((res.get("limits") or {}).get("memory")) or 0
            req_cpu += cpu_cores((res.get("requests") or {}).get("cpu")) or 0
            req_mem += bytes_((res.get("requests") or {}).get("memory")) or 0
        rows.append({"namespace": key[0], "name": key[1], "cpu": cpu, "memory": mem,
                     "cpuRequest": req_cpu or None, "memoryRequest": req_mem or None,
                     "cpuLimit": lim_cpu or None, "memoryLimit": lim_mem or None,
                     "memoryLimitRatio": (mem / lim_mem) if lim_mem else None,
                     "node": ((pod or {}).get("spec") or {}).get("nodeName")})  # fmt: skip
    rows.sort(key=lambda r: r["memory" if sort == "memory" else "cpu"], reverse=True)
    return {"metricsServer": True, "pods": rows[:limit], "total": len(rows)}


def storage_overview(k8s: KubernetesService, prom: Prometheus) -> dict[str, Any]:
    data, partial = k8s.snapshot(kinds=["pvs", "pvcs", "storageclasses"])
    pvc_usage: dict[tuple[str, str], float] = {}
    prom_error = None
    if prom.configured:
        try:
            for r in prom.query("pvc_used_ratio"):
                pvc_usage[(r["labels"].get("namespace", ""), r["labels"].get("persistentvolumeclaim", ""))] = r["value"]
        except MetricsUnavailable as exc:
            prom_error = exc.message
    pvcs = []
    for p in data["pvcs"]:
        meta, spec, st = p["metadata"], p.get("spec") or {}, p.get("status") or {}
        pvcs.append({"namespace": meta.get("namespace"), "name": meta["name"], "status": st.get("phase"),
                     "capacity": bytes_((st.get("capacity") or {}).get("storage") or
                                        ((spec.get("resources") or {}).get("requests") or {}).get("storage")),
                     "storageClass": spec.get("storageClassName"), "volume": spec.get("volumeName"),
                     "usedRatio": pvc_usage.get((meta.get("namespace"), meta["name"]))})  # fmt: skip
    by_class: dict[str, dict[str, Any]] = {}
    for pv in data["pvs"]:
        spec = pv.get("spec") or {}
        sc = spec.get("storageClassName") or "(none)"
        e = by_class.setdefault(sc, {"storageClass": sc, "volumes": 0, "capacity": 0})
        e["volumes"] += 1
        e["capacity"] += bytes_((spec.get("capacity") or {}).get("storage")) or 0
    return {"pvcs": pvcs, "byClass": list(by_class.values()), "storageClasses": len(data["storageclasses"]),
            "usageSource": "prometheus" if prom.configured and not prom_error else None,
            "prometheusError": prom_error, "partial": partial}  # fmt: skip
