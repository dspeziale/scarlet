"""Per-kind summaries: the "simple view" of a resource, with a computed health status.

Health values: healthy | progressing | degraded | failed | pending | completed | suspended | unknown.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .quantity import bytes_, cpu_cores


def _meta(obj: dict[str, Any]) -> dict[str, Any]:
    return obj.get("metadata") or {}


def created(obj: dict[str, Any]) -> str | None:
    return _meta(obj).get("creationTimestamp")


def age_seconds(ts: str | None) -> int | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(UTC) - dt).total_seconds()))


def condition(obj: dict[str, Any], ctype: str) -> dict[str, Any] | None:
    for c in (obj.get("status") or {}).get("conditions") or []:
        if c.get("type") == ctype:
            return c
    return None


def controller_of(obj: dict[str, Any]) -> dict[str, Any] | None:
    for ref in _meta(obj).get("ownerReferences") or []:
        if ref.get("controller"):
            return ref
    refs = _meta(obj).get("ownerReferences") or []
    return refs[0] if refs else None


def top_owner(pod: dict[str, Any]) -> dict[str, str] | None:
    """Pod -> ReplicaSet -> Deployment is resolved by name (the RS name is <deployment>-<hash>)."""
    ref = controller_of(pod)
    if not ref:
        return None
    if ref.get("kind") == "ReplicaSet":
        rs = ref.get("name", "")
        h = (_meta(pod).get("labels") or {}).get("pod-template-hash")
        if h and rs.endswith("-" + h):
            return {"kind": "Deployment", "name": rs[: -len(h) - 1]}
        return {"kind": "ReplicaSet", "name": rs}
    if ref.get("kind") == "Job":
        return {"kind": "Job", "name": ref.get("name", "")}
    return {"kind": ref.get("kind", ""), "name": ref.get("name", "")}


# ---------------------------------------------------------------- pods
def pod_reason(pod: dict[str, Any]) -> str:
    """Status string as kubectl shows it (CrashLoopBackOff, Running, Completed, ...)."""
    status = pod.get("status") or {}
    reason = status.get("reason") or status.get("phase") or "Unknown"
    if _meta(pod).get("deletionTimestamp"):
        return "Terminating"
    for i, cs in enumerate(status.get("initContainerStatuses") or []):
        state = cs.get("state") or {}
        term = state.get("terminated")
        if term and term.get("exitCode") == 0:
            continue
        if term:
            return f"Init:{term.get('reason') or 'Error'}"
        waiting = state.get("waiting")
        if waiting and waiting.get("reason") not in (None, "PodInitializing"):
            return f"Init:{waiting['reason']}"
        n = len((pod.get("spec") or {}).get("initContainers") or [])
        return f"Init:{i}/{n}"
    running = False
    for cs in reversed(status.get("containerStatuses") or []):
        state = cs.get("state") or {}
        if state.get("waiting", {}).get("reason"):
            reason = state["waiting"]["reason"]
        elif state.get("terminated"):
            t = state["terminated"]
            reason = t.get("reason") or (f"Signal:{t['signal']}" if t.get("signal") else f"ExitCode:{t.get('exitCode')}")
        elif state.get("running") and cs.get("ready"):
            running = True
    if reason == "Completed" and running:
        reason = "Running"
    if status.get("phase") == "Pending" and not (pod.get("spec") or {}).get("nodeName"):
        cond = condition(pod, "PodScheduled")
        if cond and cond.get("reason") == "Unschedulable":
            return "Pending"
    return reason


_FAILED_REASONS = {"CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "OOMKilled", "Error",
                   "CreateContainerConfigError", "CreateContainerError", "InvalidImageName", "RunContainerError",
                   "ContainerCannotRun", "Evicted", "Failed", "NodeLost", "Unknown"}  # fmt: skip


def pod_health(pod: dict[str, Any]) -> str:
    reason = pod_reason(pod)
    phase = (pod.get("status") or {}).get("phase")
    if reason in _FAILED_REASONS or reason.startswith(("Init:Err", "Init:Crash", "Init:Image", "ExitCode", "Signal")):
        return "failed"
    if phase == "Succeeded":
        return "completed"
    if reason == "Terminating":
        return "progressing"
    if phase == "Pending" or reason.startswith("Init:") or reason == "ContainerCreating":
        return "pending"
    if phase == "Running":
        ready = condition(pod, "Ready")
        if ready and ready.get("status") == "True":
            return "healthy"
        return "degraded"
    return "unknown"


def container_rows(pod: dict[str, Any]) -> list[dict[str, Any]]:
    statuses = {cs["name"]: cs for cs in (pod.get("status") or {}).get("containerStatuses") or []}
    rows = []
    for c in (pod.get("spec") or {}).get("containers") or []:
        cs = statuses.get(c["name"], {})
        state = cs.get("state") or {}
        state_name = next(iter(state), "unknown")
        detail = state.get(state_name) or {}
        res = c.get("resources") or {}
        rows.append({
            "name": c["name"],
            "image": c.get("image"),
            "ready": bool(cs.get("ready")),
            "restarts": cs.get("restartCount", 0),
            "state": state_name,
            "reason": detail.get("reason"),
            "message": detail.get("message"),
            "exitCode": detail.get("exitCode"),
            "lastState": cs.get("lastState") or {},
            "ports": [p.get("containerPort") for p in c.get("ports") or []],
            "requests": res.get("requests") or {},
            "limits": res.get("limits") or {},
            "readinessProbe": bool(c.get("readinessProbe")),
            "livenessProbe": bool(c.get("livenessProbe")),
            "startupProbe": bool(c.get("startupProbe")),
        })  # fmt: skip
    return rows


def _pod(o: dict[str, Any]) -> dict[str, Any]:
    st = o.get("status") or {}
    css = st.get("containerStatuses") or []
    return {
        "status": pod_reason(o),
        "ready": f"{sum(1 for c in css if c.get('ready'))}/{len((o.get('spec') or {}).get('containers') or [])}",
        "restarts": sum(c.get("restartCount", 0) for c in css),
        "node": (o.get("spec") or {}).get("nodeName"),
        "podIP": st.get("podIP"),
        "owner": top_owner(o),
        "qosClass": st.get("qosClass"),
        "containers": container_rows(o),
        "_health": pod_health(o),
    }


# ---------------------------------------------------------------- workloads
def _deployment(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    desired = spec.get("replicas", 1)
    ready = st.get("readyReplicas", 0) or 0
    available = st.get("availableReplicas", 0) or 0
    updated = st.get("updatedReplicas", 0) or 0
    progressing = condition(o, "Progressing") or {}
    if spec.get("paused"):
        health = "suspended"
    elif progressing.get("reason") == "ProgressDeadlineExceeded":
        health = "failed"
    elif desired == 0:
        health = "suspended"
    elif available == 0:
        health = "failed"
    elif available < desired:
        health = "degraded"
    elif updated < desired or (st.get("observedGeneration", 0) < _meta(o).get("generation", 0)):
        health = "progressing"
    else:
        health = "healthy"
    return {
        "replicas": desired,
        "ready": f"{ready}/{desired}",
        "readyReplicas": ready,
        "availableReplicas": available,
        "updatedReplicas": updated,
        "unavailableReplicas": st.get("unavailableReplicas", max(0, desired - available)),
        "images": _images(spec.get("template")),
        "strategy": (spec.get("strategy") or {}).get("type"),
        "paused": bool(spec.get("paused")),
        "revision": (_meta(o).get("annotations") or {}).get("deployment.kubernetes.io/revision"),
        "selector": (spec.get("selector") or {}).get("matchLabels") or {},
        "_health": health,
    }


def _statefulset(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    desired = spec.get("replicas", 1)
    ready = st.get("readyReplicas", 0) or 0
    health = ("suspended" if desired == 0 else "failed" if ready == 0 else "degraded" if ready < desired
              else "healthy")  # fmt: skip
    return {"replicas": desired, "ready": f"{ready}/{desired}", "readyReplicas": ready,
            "images": _images(spec.get("template")), "serviceName": spec.get("serviceName"),
            "selector": (spec.get("selector") or {}).get("matchLabels") or {},
            "volumeClaimTemplates": [t.get("metadata", {}).get("name") for t in spec.get("volumeClaimTemplates") or []],
            "_health": health}  # fmt: skip


def _daemonset(o: dict[str, Any]) -> dict[str, Any]:
    st = o.get("status") or {}
    desired = st.get("desiredNumberScheduled", 0) or 0
    ready = st.get("numberReady", 0) or 0
    health = "healthy" if ready >= desired else ("failed" if ready == 0 and desired > 0 else "degraded")
    return {"desired": desired, "ready": f"{ready}/{desired}", "readyReplicas": ready,
            "available": st.get("numberAvailable", 0) or 0, "unavailable": st.get("numberUnavailable", 0) or 0,
            "images": _images((o.get("spec") or {}).get("template")),
            "selector": ((o.get("spec") or {}).get("selector") or {}).get("matchLabels") or {},
            "_health": health}  # fmt: skip


def _replicaset(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    desired = spec.get("replicas", 0)
    ready = st.get("readyReplicas", 0) or 0
    return {"replicas": desired, "ready": f"{ready}/{desired}", "images": _images(spec.get("template")),
            "revision": (_meta(o).get("annotations") or {}).get("deployment.kubernetes.io/revision"),
            "owner": controller_of(o),
            "_health": "healthy" if ready >= desired else ("failed" if ready == 0 else "degraded")}  # fmt: skip


def _job(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    completions = spec.get("completions", 1)
    succeeded = st.get("succeeded", 0) or 0
    failed_c = condition(o, "Failed")
    complete_c = condition(o, "Complete")
    if failed_c and failed_c.get("status") == "True":
        health = "failed"
    elif complete_c and complete_c.get("status") == "True":
        health = "completed"
    elif spec.get("suspend"):
        health = "suspended"
    else:
        health = "progressing"
    duration = None
    if st.get("startTime") and st.get("completionTime"):
        a, b = age_seconds(st["startTime"]), age_seconds(st["completionTime"])
        duration = (a - b) if a is not None and b is not None else None
    return {"completions": f"{succeeded}/{completions}", "active": st.get("active", 0) or 0,
            "failed": st.get("failed", 0) or 0, "duration": duration, "owner": controller_of(o),
            "images": _images(spec.get("template")),
            "failReason": failed_c.get("reason") if failed_c else None, "_health": health}  # fmt: skip


def _cronjob(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    return {"schedule": spec.get("schedule"), "timeZone": spec.get("timeZone"), "suspend": bool(spec.get("suspend")),
            "active": len(st.get("active") or []), "lastScheduleTime": st.get("lastScheduleTime"),
            "lastSuccessfulTime": st.get("lastSuccessfulTime"),
            "images": _images(((spec.get("jobTemplate") or {}).get("spec") or {}).get("template")),
            "_health": "suspended" if spec.get("suspend") else "healthy"}  # fmt: skip


def _images(template: dict[str, Any] | None) -> list[str]:
    spec = (template or {}).get("spec") or {}
    return [c.get("image", "") for c in spec.get("containers") or []]


# ---------------------------------------------------------------- networking
def _service(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    lb = [i.get("ip") or i.get("hostname") for i in ((st.get("loadBalancer") or {}).get("ingress") or [])]
    ports = [
        f"{p.get('port')}{':' + str(p['nodePort']) if p.get('nodePort') else ''}/{p.get('protocol', 'TCP')}"
        for p in spec.get("ports") or []
    ]
    health = "pending" if spec.get("type") == "LoadBalancer" and not lb else "healthy"
    return {"type": spec.get("type", "ClusterIP"), "clusterIP": spec.get("clusterIP"), "externalIPs": lb +
            (spec.get("externalIPs") or []), "ports": ports, "selector": spec.get("selector") or {},
            "_health": health}  # fmt: skip


def _ingress(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    rules = []
    for r in spec.get("rules") or []:
        for p in (r.get("http") or {}).get("paths") or []:
            svc = (p.get("backend") or {}).get("service") or {}
            port = svc.get("port") or {}
            rules.append({"host": r.get("host") or "*", "path": p.get("path", "/"), "service": svc.get("name"),
                          "port": port.get("number") or port.get("name")})  # fmt: skip
    addrs = [i.get("ip") or i.get("hostname") for i in ((st.get("loadBalancer") or {}).get("ingress") or [])]
    tls_hosts = [h for t in spec.get("tls") or [] for h in t.get("hosts") or []]
    return {"class": spec.get("ingressClassName"), "hosts": sorted({r["host"] for r in rules}), "rules": rules,
            "addresses": addrs, "tls": tls_hosts, "_health": "healthy" if addrs else "pending"}  # fmt: skip


def _endpoints(o: dict[str, Any]) -> dict[str, Any]:
    ready = not_ready = 0
    addrs = []
    for s in o.get("subsets") or []:
        ready += len(s.get("addresses") or [])
        not_ready += len(s.get("notReadyAddresses") or [])
        addrs += [a.get("ip") for a in s.get("addresses") or []]
    return {"ready": ready, "notReady": not_ready, "addresses": addrs[:20],
            "_health": "healthy" if ready else ("degraded" if not_ready else "unknown")}  # fmt: skip


# ---------------------------------------------------------------- storage / config
def _pv(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    claim = spec.get("claimRef") or {}
    phase = st.get("phase", "Unknown")
    return {"capacity": (spec.get("capacity") or {}).get("storage"), "accessModes": spec.get("accessModes") or [],
            "reclaimPolicy": spec.get("persistentVolumeReclaimPolicy"), "status": phase,
            "claim": f"{claim.get('namespace')}/{claim.get('name')}" if claim else None,
            "storageClass": spec.get("storageClassName"),
            "_health": {"Bound": "healthy", "Available": "healthy", "Released": "degraded", "Failed": "failed"}.get(
                phase, "unknown")}  # fmt: skip


def _pvc(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    phase = st.get("phase", "Unknown")
    return {"status": phase, "volume": spec.get("volumeName"),
            "capacity": (st.get("capacity") or {}).get("storage") or ((spec.get("resources") or {}).get("requests") or {}).get("storage"),
            "accessModes": spec.get("accessModes") or [], "storageClass": spec.get("storageClassName"),
            "_health": {"Bound": "healthy", "Pending": "pending", "Lost": "failed"}.get(phase, "unknown")}  # fmt: skip


def _storageclass(o: dict[str, Any]) -> dict[str, Any]:
    ann = _meta(o).get("annotations") or {}
    return {"provisioner": o.get("provisioner"), "reclaimPolicy": o.get("reclaimPolicy", "Delete"),
            "volumeBindingMode": o.get("volumeBindingMode", "Immediate"),
            "allowVolumeExpansion": bool(o.get("allowVolumeExpansion")),
            "default": ann.get("storageclass.kubernetes.io/is-default-class") == "true", "_health": "healthy"}  # fmt: skip


def _configmap(o: dict[str, Any]) -> dict[str, Any]:
    keys = sorted({*(o.get("data") or {}), *(o.get("binaryData") or {})})
    return {"keys": keys, "keyCount": len(keys), "_health": "healthy"}


def _secret(o: dict[str, Any]) -> dict[str, Any]:
    keys = sorted(o.get("data") or {})
    return {"type": o.get("type", "Opaque"), "keys": keys, "keyCount": len(keys), "_health": "healthy"}


# ---------------------------------------------------------------- cluster
def node_ready(node: dict[str, Any]) -> bool:
    c = condition(node, "Ready")
    return bool(c and c.get("status") == "True")


def _node(o: dict[str, Any]) -> dict[str, Any]:
    st, spec = o.get("status") or {}, o.get("spec") or {}
    labels = _meta(o).get("labels") or {}
    roles = sorted(k.split("/", 1)[1] for k in labels if k.startswith("node-role.kubernetes.io/")) or ["worker"]
    pressures = [c["type"] for c in st.get("conditions") or [] if c.get("type") != "Ready" and c.get("status") == "True"]
    ready = node_ready(o)
    alloc = st.get("allocatable") or {}
    info = st.get("nodeInfo") or {}
    addrs = {a.get("type"): a.get("address") for a in st.get("addresses") or []}
    if not ready:
        health = "failed"
    elif pressures or spec.get("unschedulable"):
        health = "degraded"
    else:
        health = "healthy"
    return {"ready": ready, "status": "Ready" if ready else "NotReady", "roles": roles,
            "unschedulable": bool(spec.get("unschedulable")), "pressures": pressures,
            "taints": [f"{t.get('key')}{'=' + t['value'] if t.get('value') else ''}:{t.get('effect')}"
                       for t in spec.get("taints") or []],
            "cpu": cpu_cores(alloc.get("cpu")), "memory": bytes_(alloc.get("memory")), "pods": alloc.get("pods"),
            "internalIP": addrs.get("InternalIP"), "kubeletVersion": info.get("kubeletVersion"),
            "osImage": info.get("osImage"), "kernelVersion": info.get("kernelVersion"),
            "containerRuntime": info.get("containerRuntimeVersion"), "_health": health}  # fmt: skip


def _namespace(o: dict[str, Any]) -> dict[str, Any]:
    phase = (o.get("status") or {}).get("phase", "Active")
    return {"status": phase, "_health": "healthy" if phase == "Active" else "progressing"}


def _event(o: dict[str, Any]) -> dict[str, Any]:
    inv = o.get("involvedObject") or o.get("regarding") or {}
    return {"type": o.get("type"), "reason": o.get("reason"), "message": o.get("message") or o.get("note"),
            "object": {"kind": inv.get("kind"), "name": inv.get("name"), "namespace": inv.get("namespace")},
            "count": o.get("count") or (o.get("series") or {}).get("count") or 1,
            "lastTimestamp": event_time(o), "source": (o.get("source") or {}).get("component") or o.get(
                "reportingController"), "_health": "degraded" if o.get("type") == "Warning" else "healthy"}  # fmt: skip


def event_time(o: dict[str, Any]) -> str | None:
    return (o.get("lastTimestamp") or o.get("eventTime") or (o.get("series") or {}).get("lastObservedTime")
            or o.get("firstTimestamp") or created(o))  # fmt: skip


def _pdb(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    allowed = st.get("disruptionsAllowed", 0)
    return {"minAvailable": spec.get("minAvailable"), "maxUnavailable": spec.get("maxUnavailable"),
            "disruptionsAllowed": allowed, "currentHealthy": st.get("currentHealthy"),
            "desiredHealthy": st.get("desiredHealthy"),
            "selector": (spec.get("selector") or {}).get("matchLabels") or {},
            "_health": "healthy" if allowed > 0 else "degraded"}  # fmt: skip


def _hpa(o: dict[str, Any]) -> dict[str, Any]:
    spec, st = o.get("spec") or {}, o.get("status") or {}
    ref = spec.get("scaleTargetRef") or {}
    return {"target": f"{ref.get('kind')}/{ref.get('name')}", "minReplicas": spec.get("minReplicas", 1),
            "maxReplicas": spec.get("maxReplicas"), "currentReplicas": st.get("currentReplicas"),
            "desiredReplicas": st.get("desiredReplicas"), "_health": "healthy"}  # fmt: skip


_SUMMARIZERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "Pod": _pod, "Deployment": _deployment, "StatefulSet": _statefulset, "DaemonSet": _daemonset,
    "ReplicaSet": _replicaset, "Job": _job, "CronJob": _cronjob, "Service": _service, "Ingress": _ingress,
    "Endpoints": _endpoints, "PersistentVolume": _pv, "PersistentVolumeClaim": _pvc,
    "StorageClass": _storageclass, "ConfigMap": _configmap, "Secret": _secret, "Node": _node,
    "Namespace": _namespace, "Event": _event, "PodDisruptionBudget": _pdb, "HorizontalPodAutoscaler": _hpa,
}  # fmt: skip


def summarize(obj: dict[str, Any]) -> dict[str, Any]:
    meta = _meta(obj)
    fn = _SUMMARIZERS.get(obj.get("kind", ""))
    extra = fn(obj) if fn else {"_health": "unknown"}
    health = extra.pop("_health")
    return {
        "kind": obj.get("kind"),
        "name": meta.get("name"),
        "namespace": meta.get("namespace"),
        "uid": meta.get("uid"),
        "createdAt": meta.get("creationTimestamp"),
        "labels": meta.get("labels") or {},
        "health": health,
        **extra,
    }
