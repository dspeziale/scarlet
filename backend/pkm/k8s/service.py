"""High-level Kubernetes operations used by the API.

- short TTL cache of list calls (dashboard bursts hit Kubernetes once), invalidated on writes
- parallel snapshot of the kinds needed by dashboard and diagnostics, tolerant to
  per-kind RBAC denials (reported as `partial`)
- sanitization of objects for display (managedFields removed, Secret values hidden)
- workload operations: scale, restart, pause/resume, rollout history and rollback,
  CronJob suspend/trigger, node cordon/uncordon/drain
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from ..config import KubernetesConfig, Settings
from ..errors import (
    AppError,
    BadRequest,
    K8sForbidden,
    K8sNotFound,
    K8sUnsupported,
    NotSupported,
    ValidationFailed,
)
from . import diagnostics, relations
from .kinds import KINDS, KindInfo, get_kind
from .provider import KubernetesProvider
from .quantity import bytes_, cpu_cores
from .summarize import node_ready, summarize

log = logging.getLogger("pkm.k8s.service")

HIDDEN = "<hidden>"
SNAPSHOT_KINDS = {
    "nodes": "nodes", "pods": "pods", "deployments": "deployments", "statefulsets": "statefulsets",
    "daemonsets": "daemonsets", "jobs": "jobs", "pvcs": "persistentvolumeclaims", "events": "events",
    "storageclasses": "storageclasses", "configmaps": "configmaps", "secrets": "secrets",
    "pvs": "persistentvolumes", "namespaces": "namespaces", "services": "services",
}  # fmt: skip


def now_rfc3339() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_provider(settings: Settings) -> KubernetesProvider:
    if settings.is_demo:
        from .demo import DemoKubernetes

        return DemoKubernetes()
    from .live import LiveKubernetes

    return LiveKubernetes(settings.kubernetes)


class KubernetesService:
    def __init__(self, provider: KubernetesProvider, cfg: KubernetesConfig) -> None:
        self._provider = provider
        self.cfg = cfg
        self._cache: dict[tuple[str, str | None, str | None], tuple[float, list[dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="k8s")
        self._generation = 0

    # ---------------------------------------------------------------- lifecycle
    @property
    def provider(self) -> KubernetesProvider:
        return self._provider

    @property
    def demo(self) -> bool:
        return self._provider.demo

    def replace_provider(self, provider: KubernetesProvider, cfg: KubernetesConfig) -> None:
        old = self._provider
        with self._lock:
            self._provider = provider
            self.cfg = cfg
            self._cache.clear()
            self._generation += 1
        old.close()

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()
            self._generation += 1

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._provider.close()

    def info(self) -> dict[str, Any]:
        return self._provider.info()

    # ---------------------------------------------------------------- reads
    def list_raw(self, kind: KindInfo, namespace: str | None = None, label_selector: str | None = None,
                 field_selector: str | None = None) -> list[dict[str, Any]]:  # fmt: skip
        key = (kind.key, namespace, f"{label_selector or ''}|{field_selector or ''}")
        ttl = self.cfg.cache_ttl_seconds
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            gen = self._generation
        if hit and ttl > 0 and now - hit[0] < ttl:
            return hit[1]
        try:
            items = self._provider.list(kind, namespace, label_selector=label_selector, field_selector=field_selector)
        except K8sNotFound as exc:
            # The collection itself does not exist: API version not served by this cluster.
            raise K8sUnsupported(
                f"{kind.kind} ({kind.api_version}) is not available on this cluster",
                params={"kind": kind.kind, "apiVersion": kind.api_version, "minVersion": kind.min_version},
                details=exc.details,
            ) from exc
        with self._lock:
            if gen == self._generation:
                self._cache[key] = (now, items)
        return items

    def get_raw(self, kind: KindInfo, name: str, namespace: str | None) -> dict[str, Any]:
        return self._provider.get(kind, name, namespace if kind.namespaced else None)

    def list_summaries(self, key: str, namespace: str | None = None, label_selector: str | None = None,
                       field_selector: str | None = None) -> dict[str, Any]:  # fmt: skip
        kind = get_kind(key)
        items = self.list_raw(kind, namespace if kind.namespaced else None, label_selector, field_selector)
        rows = [summarize(o) for o in items]
        if key == "events":
            rows.sort(key=lambda r: r.get("lastTimestamp") or "", reverse=True)
        return {"kind": kind.public(), "items": rows, "count": len(rows)}

    def detail(self, key: str, name: str, namespace: str | None, *, reveal: bool = False,
               managed_fields: bool = False) -> dict[str, Any]:  # fmt: skip
        kind = get_kind(key)
        obj = self.get_raw(kind, name, namespace)
        return {"kind": kind.public(), "summary": summarize(obj),
                "object": sanitize(obj, reveal=reveal, managed_fields=managed_fields)}  # fmt: skip

    def events_for(self, key: str, name: str, namespace: str | None) -> list[dict[str, Any]]:
        kind = get_kind(key)
        ns = namespace if kind.namespaced else None
        fs = f"involvedObject.kind={kind.kind},involvedObject.name={name}"
        items = self.list_raw(KINDS["events"], ns or ("default" if kind.kind == "Node" else None), field_selector=fs)
        if kind.kind == "Node" and not items:
            items = self.list_raw(KINDS["events"], None, field_selector=fs)
        rows = [summarize(e) for e in items]
        rows.sort(key=lambda r: r.get("lastTimestamp") or "", reverse=True)
        return rows

    def snapshot(self, namespace: str | None = None, *, kinds: list[str] | None = None,
                 metrics: bool = False) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:  # fmt: skip
        """Fetch several kinds in parallel. Returns (data, partial_errors)."""
        wanted = kinds or list(SNAPSHOT_KINDS)
        futures = {}
        for name in wanted:
            kind = KINDS[SNAPSHOT_KINDS[name]]
            futures[name] = self._pool.submit(self.list_raw, kind, namespace if kind.namespaced else None)
        if metrics:
            futures["pod_metrics"] = self._pool.submit(self._provider.pod_metrics, namespace)
        data: dict[str, list[dict[str, Any]]] = {}
        partial: list[dict[str, Any]] = []
        fatal: AppError | None = None
        for name, fut in futures.items():
            try:
                data[name] = fut.result(timeout=self.cfg.request_timeout + self.cfg.connect_timeout + 5) or []
            except (K8sForbidden, K8sUnsupported) as exc:
                data[name] = []
                partial.append({"kind": name, "code": exc.code, "message": exc.message})
            except AppError as exc:
                fatal = fatal or exc
            except TimeoutError:
                from ..errors import K8sTimeout

                fatal = fatal or K8sTimeout("Kubernetes API did not answer in time")
        if fatal is not None:
            raise fatal
        return data, partial

    # ---------------------------------------------------------------- dashboard
    def issues(self, namespace: str | None = None) -> tuple[list[diagnostics.Issue], list[dict[str, Any]]]:
        data, partial = self.snapshot(namespace, metrics=True)
        return diagnostics.analyze(data), partial

    def overview(self) -> dict[str, Any]:
        data, partial = self.snapshot(metrics=False)
        issues = diagnostics.analyze(data)
        nodes = data.get("nodes", [])
        pods = data.get("pods", [])
        pod_rows = [summarize(p) for p in pods]
        dep_rows = [summarize(d) for d in data.get("deployments", [])]
        sts_rows = [summarize(d) for d in data.get("statefulsets", [])]
        ds_rows = [summarize(d) for d in data.get("daemonsets", [])]
        warnings = [summarize(e) for e in data.get("events", []) if e.get("type") == "Warning"]
        warnings.sort(key=lambda r: r.get("lastTimestamp") or "", reverse=True)
        restarts = sorted((r for r in pod_rows if r.get("restarts")), key=lambda r: r["restarts"], reverse=True)
        node_metrics = self._provider.node_metrics()
        alloc_cpu = sum(cpu_cores(((n.get("status") or {}).get("allocatable") or {}).get("cpu")) or 0
                        for n in nodes if node_ready(n))  # fmt: skip
        alloc_mem = sum(bytes_(((n.get("status") or {}).get("allocatable") or {}).get("memory")) or 0
                        for n in nodes if node_ready(n))  # fmt: skip
        req_cpu = req_mem = 0.0
        for p in pods:
            if (p.get("status") or {}).get("phase") in ("Running", "Pending"):
                for c in (p.get("spec") or {}).get("containers") or []:
                    r = (c.get("resources") or {}).get("requests") or {}
                    req_cpu += cpu_cores(r.get("cpu")) or 0
                    req_mem += bytes_(r.get("memory")) or 0
        usage = None
        if node_metrics is not None:
            usage = {
                "cpu": sum(cpu_cores((m.get("usage") or {}).get("cpu")) or 0 for m in node_metrics),
                "memory": sum(bytes_((m.get("usage") or {}).get("memory")) or 0 for m in node_metrics),
            }
        pvs = data.get("pvs", [])
        pvcs = data.get("pvcs", [])

        def count(rows: list[dict[str, Any]], *health: str) -> int:
            return sum(1 for r in rows if r["health"] in health)

        return {
            "cluster": self._provider.info(),
            "partial": partial,
            "nodes": {"total": len(nodes), "ready": sum(1 for n in nodes if node_ready(n)),
                      "notReady": sum(1 for n in nodes if not node_ready(n)),
                      "cordoned": sum(1 for n in nodes if (n.get("spec") or {}).get("unschedulable"))},
            "namespaces": len(data.get("namespaces", [])),
            "pods": {"total": len(pod_rows), "running": sum(1 for p in pods if (p.get("status") or {}).get("phase") == "Running"),
                     "healthy": count(pod_rows, "healthy"), "failed": count(pod_rows, "failed"),
                     "pending": count(pod_rows, "pending"), "completed": count(pod_rows, "completed")},
            "deployments": {"total": len(dep_rows), "healthy": count(dep_rows, "healthy"),
                            "degraded": count(dep_rows, "degraded", "progressing"), "failed": count(dep_rows, "failed")},
            "statefulsets": {"total": len(sts_rows), "degraded": count(sts_rows, "degraded", "failed")},
            "daemonsets": {"total": len(ds_rows), "degraded": count(ds_rows, "degraded", "failed")},
            "services": len(data.get("services", [])),
            "resources": {"allocatableCpu": alloc_cpu, "allocatableMemory": alloc_mem, "requestedCpu": req_cpu,
                          "requestedMemory": req_mem, "usage": usage, "metricsAvailable": node_metrics is not None},
            "storage": {"pvCount": len(pvs),
                        "pvCapacity": sum(bytes_(((p.get("spec") or {}).get("capacity") or {}).get("storage")) or 0 for p in pvs),
                        "pvcBound": sum(1 for p in pvcs if (p.get("status") or {}).get("phase") == "Bound"),
                        "pvcPending": sum(1 for p in pvcs if (p.get("status") or {}).get("phase") == "Pending"),
                        "pvcTotal": len(pvcs)},
            "restarts": {"total": sum(r.get("restarts", 0) for r in pod_rows),
                         "top": [{k: r.get(k) for k in ("name", "namespace", "restarts", "status")} for r in restarts[:5]]},
            "events": {"warnings": len(warnings), "recent": warnings[:10]},
            "issues": {"counts": diagnostics.summary_counts(issues), "top": [i.to_dict() for i in issues[:8]]},
        }  # fmt: skip

    def relations(self, key: str, name: str, namespace: str | None) -> dict[str, Any]:
        kind = get_kind(key)
        root = self.get_raw(kind, name, namespace)
        ns = (root.get("metadata") or {}).get("namespace")
        wanted = ["pods", "configmaps", "secrets", "services", "pvcs", "nodes", "pvs", "storageclasses"]
        data, _ = self.snapshot(ns, kinds=wanted)
        extra = {}
        for k in ("replicasets", "jobs", "ingresses"):
            try:
                extra[k] = self.list_raw(KINDS[k], ns) if ns else []
            except (K8sForbidden, K8sUnsupported):
                extra[k] = []
        return relations.build(root, {**data, **extra})

    def diagnose(self, key: str, name: str, namespace: str | None) -> list[dict[str, Any]]:
        kind = get_kind(key)
        obj = self.get_raw(kind, name, namespace)
        issues, _ = self.issues((obj.get("metadata") or {}).get("namespace"))
        out = []
        for i in issues:
            if (i.kind == kind.kind and i.name == name) or (i.owner and i.owner.get("kind") == kind.kind
                                                            and i.owner.get("name") == name) or (kind.kind == "Node" and i.node == name) or (kind.kind == "Pod" and name in i.affected):  # fmt: skip
                out.append(i.to_dict())
        return out

    # ---------------------------------------------------------------- writes
    def _after_write(self) -> None:
        self.invalidate()

    def apply(self, manifest: dict[str, Any], *, dry_run: bool, force: bool = False) -> dict[str, Any]:
        result = self._provider.apply(manifest, dry_run=dry_run, force=force)
        if not dry_run:
            self._after_write()
        return result

    def delete(self, key: str, name: str, namespace: str | None) -> None:
        kind = get_kind(key)
        self._provider.delete(kind, name, namespace if kind.namespaced else None)
        self._after_write()

    def scale(self, key: str, name: str, namespace: str, replicas: int) -> dict[str, Any]:
        kind = get_kind(key)
        if kind.kind not in ("Deployment", "StatefulSet"):
            raise NotSupported(f"{kind.kind} cannot be scaled", params={"kind": kind.kind})
        res = self._provider.patch(kind, name, namespace, {"spec": {"replicas": replicas}})
        self._after_write()
        return summarize(res)

    def restart(self, key: str, name: str, namespace: str) -> dict[str, Any]:
        kind = get_kind(key)
        if kind.kind not in ("Deployment", "StatefulSet", "DaemonSet"):
            raise NotSupported(f"{kind.kind} cannot be restarted with a rollout", params={"kind": kind.kind})
        body = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now_rfc3339()}}}}}
        res = self._provider.patch(kind, name, namespace, body)
        self._after_write()
        return summarize(res)

    def set_paused(self, name: str, namespace: str, paused: bool) -> dict[str, Any]:
        res = self._provider.patch(KINDS["deployments"], name, namespace, {"spec": {"paused": paused}})
        self._after_write()
        return summarize(res)

    def rollout(self, name: str, namespace: str) -> dict[str, Any]:
        dep = self.get_raw(KINDS["deployments"], name, namespace)
        uid = dep["metadata"]["uid"]
        rss = [rs for rs in self._provider.list(KINDS["replicasets"], namespace)
               if any(r.get("uid") == uid for r in rs["metadata"].get("ownerReferences") or [])]  # fmt: skip
        current_rev = (dep["metadata"].get("annotations") or {}).get("deployment.kubernetes.io/revision")
        history = []
        for rs in rss:
            ann = rs["metadata"].get("annotations") or {}
            rev = ann.get("deployment.kubernetes.io/revision")
            if rev is None:
                continue
            tmpl = (rs.get("spec") or {}).get("template") or {}
            history.append({
                "revision": int(rev),
                "replicaSet": rs["metadata"]["name"],
                "createdAt": rs["metadata"].get("creationTimestamp"),
                "images": [c.get("image") for c in (tmpl.get("spec") or {}).get("containers") or []],
                "changeCause": ann.get("kubernetes.io/change-cause"),
                "replicas": (rs.get("status") or {}).get("replicas", 0),
                "current": rev == current_rev,
                "template": _clean_template(tmpl),
            })  # fmt: skip
        history.sort(key=lambda h: h["revision"], reverse=True)
        s = summarize(dep)
        conds = {c.get("type"): c for c in (dep.get("status") or {}).get("conditions") or []}
        return {"summary": s, "revision": current_rev, "paused": s["paused"], "history": history,
                "strategy": (dep.get("spec") or {}).get("strategy") or {},
                "conditions": list(conds.values()),
                "complete": s["health"] == "healthy"}  # fmt: skip

    def rollback(self, name: str, namespace: str, revision: int | None) -> dict[str, Any]:
        info = self.rollout(name, namespace)
        history = info["history"]
        current = next((h for h in history if h["current"]), None)
        if revision is None:
            candidates = [h for h in history if not h["current"]]
            if not candidates:
                raise BadRequest("there is no previous revision to roll back to", params={"rule": "no_history"})
            target = candidates[0]
        else:
            target = next((h for h in history if h["revision"] == revision), None)
            if target is None:
                raise ValidationFailed(f"revision {revision} not found", params={"field": "revision"})
            if current and target["revision"] == current["revision"]:
                raise BadRequest("this revision is already the current one", params={"rule": "already_current"})
        if info["paused"]:
            raise BadRequest("resume the deployment before rolling back", params={"rule": "paused"})
        patch = [{"op": "replace", "path": "/spec/template", "value": target["template"]}]
        res = self._provider.patch(KINDS["deployments"], name, namespace, patch, patch_type="json")
        self._after_write()
        return {"summary": summarize(res), "revision": target["revision"]}

    def set_cronjob_suspended(self, name: str, namespace: str, suspend: bool) -> dict[str, Any]:
        res = self._provider.patch(KINDS["cronjobs"], name, namespace, {"spec": {"suspend": suspend}})
        self._after_write()
        return summarize(res)

    def trigger_cronjob(self, name: str, namespace: str) -> dict[str, Any]:
        cj = self.get_raw(KINDS["cronjobs"], name, namespace)
        tmpl = copy.deepcopy((cj.get("spec") or {}).get("jobTemplate") or {})
        job_name = f"{name}-manual-{int(time.time()) % 10**8}"[:63]
        job = {"apiVersion": "batch/v1", "kind": "Job",
               "metadata": {"name": job_name, "namespace": namespace,
                            "labels": (tmpl.get("metadata") or {}).get("labels") or {},
                            "annotations": {"cronjob.kubernetes.io/instantiate": "manual"},
                            "ownerReferences": [{"apiVersion": "batch/v1", "kind": "CronJob", "name": name,
                                                 "uid": cj["metadata"]["uid"], "controller": True}]},
               "spec": tmpl.get("spec") or {}}  # fmt: skip
        res = self._provider.create(job)
        self._after_write()
        return summarize(res)

    def set_cordon(self, name: str, unschedulable: bool) -> dict[str, Any]:
        res = self._provider.patch(KINDS["nodes"], name, None, {"spec": {"unschedulable": unschedulable or None}})
        self._after_write()
        return summarize(res)

    def drain_plan(self, name: str) -> dict[str, Any]:
        self.get_raw(KINDS["nodes"], name, None)
        pods = self._provider.list(KINDS["pods"], None, field_selector=f"spec.nodeName={name}")
        plan = []
        for p in pods:
            meta = p["metadata"]
            owner = next((r for r in meta.get("ownerReferences") or [] if r.get("controller")), None)
            phase = (p.get("status") or {}).get("phase")
            entry = {"name": meta["name"], "namespace": meta.get("namespace"),
                     "owner": f"{owner['kind']}/{owner['name']}" if owner else None, "action": "evict", "reason": None}  # fmt: skip
            if "kubernetes.io/config.mirror" in (meta.get("annotations") or {}):
                entry.update(action="skip", reason="mirror_pod")
            elif owner and owner.get("kind") == "DaemonSet":
                entry.update(action="skip", reason="daemonset")
            elif phase in ("Succeeded", "Failed"):
                entry.update(action="evict", reason="finished")
            elif not owner:
                entry.update(action="blocked", reason="unmanaged")
            elif any("emptyDir" in v for v in (p.get("spec") or {}).get("volumes") or []):
                entry.update(action="blocked", reason="emptydir")
            plan.append(entry)
        return {"node": name, "pods": plan}

    def drain(self, name: str, *, force_unmanaged: bool, delete_emptydir: bool, timeout_seconds: int,
              progress: Callable[[str, dict[str, Any]], None], cancelled: Callable[[], bool]) -> dict[str, Any]:  # fmt: skip
        plan = self.drain_plan(name)
        blocked = [p for p in plan["pods"] if p["action"] == "blocked" and not (
            (p["reason"] == "unmanaged" and force_unmanaged) or (p["reason"] == "emptydir" and delete_emptydir))]  # fmt: skip
        if blocked:
            raise BadRequest("some pods cannot be evicted safely", params={"rule": "drain_blocked", "pods": blocked})
        self.set_cordon(name, True)
        progress("cordoned", {"node": name})
        pending = [p for p in plan["pods"] if p["action"] != "skip"]
        deadline = time.monotonic() + timeout_seconds
        results: dict[str, str] = {}
        while pending and time.monotonic() < deadline and not cancelled():
            still = []
            for p in pending:
                key = f"{p['namespace']}/{p['name']}"
                try:
                    self._provider.evict(p["name"], p["namespace"])
                    results[key] = "evicted"
                    progress("evicted", {"pod": key})
                except K8sNotFound:
                    results[key] = "gone"
                except AppError as exc:
                    if exc.params.get("status") == 429 or exc.code == "k8s_conflict":
                        results[key] = "blocked_by_pdb"
                        progress("retry", {"pod": key, "reason": "pdb"})
                        still.append(p)
                    else:
                        results[key] = f"error: {exc.message}"
                        progress("error", {"pod": key, "message": exc.message})
            pending = still
            if pending:
                time.sleep(5)
        self._after_write()
        timed_out = bool(pending)
        return {"node": name, "results": results, "timedOut": timed_out and not cancelled(),
                "cancelled": cancelled(), "remaining": [f"{p['namespace']}/{p['name']}" for p in pending],
                "skipped": [f"{p['namespace']}/{p['name']}" for p in plan["pods"] if p["action"] == "skip"]}  # fmt: skip

    # ---------------------------------------------------------------- metrics
    def node_metrics(self) -> list[dict[str, Any]] | None:
        return self._provider.node_metrics()

    def pod_metrics(self, namespace: str | None = None) -> list[dict[str, Any]] | None:
        return self._provider.pod_metrics(namespace)

    # ---------------------------------------------------------------- logs
    def pod_logs(self, name: str, namespace: str, **kw: Any) -> str:
        return self._provider.pod_logs(name, namespace, **kw)

    def stream_pod_logs(self, name: str, namespace: str, **kw: Any) -> Any:
        return self._provider.stream_pod_logs(name, namespace, **kw)


def _clean_template(tmpl: dict[str, Any]) -> dict[str, Any]:
    t = copy.deepcopy(tmpl)
    labels = (t.get("metadata") or {}).get("labels") or {}
    labels.pop("pod-template-hash", None)
    return t


_KEY_ORDER = ("apiVersion", "kind", "metadata", "spec", "data", "stringData", "type")


def sanitize(obj: dict[str, Any], *, reveal: bool = False, managed_fields: bool = False) -> dict[str, Any]:
    src = copy.deepcopy(obj)
    # Canonical key order (apiVersion, kind, metadata, spec, ... status) for readable YAML.
    o = {k: src[k] for k in _KEY_ORDER if k in src}
    o.update({k: v for k, v in src.items() if k not in o and k != "status"})
    if "status" in src:
        o["status"] = src["status"]
    meta = o.get("metadata") or {}
    if not managed_fields:
        meta.pop("managedFields", None)
    ann = meta.get("annotations") or {}
    # last-applied-configuration of a Secret contains its values in clear text
    if o.get("kind") == "Secret" and not reveal:
        ann.pop("kubectl.kubernetes.io/last-applied-configuration", None)
        for field in ("data", "stringData"):
            if isinstance(o.get(field), dict):
                o[field] = dict.fromkeys(o[field], HIDDEN)
    return o


def validate_manifest_shape(doc: Any, index: int) -> dict[str, Any]:
    from .kinds import kind_for_manifest
    from .naming import validate_name

    if not isinstance(doc, dict):
        raise ValidationFailed(f"document {index + 1} is not a mapping", params={"document": index + 1})
    for f in ("apiVersion", "kind", "metadata"):
        if f not in doc:
            raise ValidationFailed(f"document {index + 1}: missing '{f}'", params={"document": index + 1, "field": f})
    meta = doc["metadata"]
    if not isinstance(meta, dict) or not meta.get("name"):
        raise ValidationFailed(f"document {index + 1}: metadata.name is required",
                               params={"document": index + 1, "field": "metadata.name"})  # fmt: skip
    info = kind_for_manifest(str(doc["apiVersion"]), str(doc["kind"]))
    validate_name(str(meta["name"]), "metadata.name", subdomain=True)
    if info.namespaced:
        if meta.get("namespace"):
            validate_name(str(meta["namespace"]), "metadata.namespace")
    elif meta.get("namespace"):
        raise ValidationFailed(f"{info.kind} is cluster-scoped: remove metadata.namespace",
                               params={"document": index + 1, "field": "metadata.namespace"})  # fmt: skip
    for f in ("uid", "resourceVersion", "creationTimestamp", "managedFields", "generation"):
        meta.pop(f, None)
    doc.pop("status", None)
    return doc
