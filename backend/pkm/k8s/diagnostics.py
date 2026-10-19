"""Automatic problem detection (Troubleshooting Center / Centro Operativo).

Pure functions over a snapshot of cluster objects. Every Issue carries:
  - severity (CRITICAL / ERROR / WARNING / INFO) and a stable reason code
  - the affected resource, the application (top owner) and the node
  - facts and *computed checks* (ok / fail / warn / unknown) derived from real data
    (container states, events, node conditions, storage classes...)
  - the actions that make sense and the guide article to read
The UI translates reason/check codes into explanations; nothing here is invented:
a check whose outcome cannot be derived from data is reported as "unknown".
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from .quantity import bytes_, cpu_cores
from .summarize import age_seconds, condition, event_time, node_ready, pod_reason, top_owner

SEVERITY_ORDER = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}

IMAGE_RE = re.compile(
    r"^(?:(?P<registry>[a-zA-Z0-9.-]+(?::[0-9]+)?)/)?(?P<repo>[a-z0-9]+(?:[._/-][a-z0-9]+)*)"
    r"(?::(?P<tag>[\w][\w.-]{0,127}))?(?:@(?P<digest>sha256:[a-f0-9]{64}))?$"
)
PUBLIC_REGISTRIES = {"docker.io", "registry-1.docker.io", "quay.io", "registry.k8s.io", "ghcr.io", "gcr.io",
                     "public.ecr.aws", "container-registry.oracle.com", "mcr.microsoft.com"}  # fmt: skip

EXIT_CODES = {0: "completed", 1: "app_error", 2: "misuse", 126: "not_executable", 127: "command_not_found",
              128: "invalid_exit", 134: "abort", 137: "killed", 139: "segfault", 143: "terminated"}  # fmt: skip


@dataclass
class Check:
    id: str
    status: str  # ok | fail | warn | unknown
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Issue:
    id: str
    severity: str
    reason: str
    kind: str
    name: str
    namespace: str | None
    owner: dict[str, str] | None = None
    node: str | None = None
    container: str | None = None
    message: str = ""
    since: str | None = None
    affected: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    checks: list[Check] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    guide: str | None = None
    likely_cause: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["checks"] = [asdict(c) for c in self.checks]
        return d


def parse_image(image: str) -> dict[str, Any]:
    m = IMAGE_RE.match(image or "")
    if not m:
        return {"valid": False}
    registry = m.group("registry")
    if registry and "." not in registry and ":" not in registry and registry != "localhost":
        # "library/nginx" style: first component is a namespace, not a registry
        repo = f"{registry}/{m.group('repo')}"
        registry = None
    else:
        repo = m.group("repo")
    return {"valid": True, "registry": registry or "docker.io", "repository": repo, "tag": m.group("tag"),
            "digest": m.group("digest")}  # fmt: skip


class _Events:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._by: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for e in events:
            inv = e.get("involvedObject") or e.get("regarding") or {}
            self._by[(inv.get("kind", ""), inv.get("namespace") or "", inv.get("name", ""))].append(e)

    def for_obj(self, kind: str, ns: str | None, name: str) -> list[dict[str, Any]]:
        evs = self._by.get((kind, ns or "", name), [])
        return sorted(evs, key=lambda e: event_time(e) or "", reverse=True)

    def messages(self, kind: str, ns: str | None, name: str, reasons: set[str] | None = None) -> list[str]:
        return [e.get("message") or "" for e in self.for_obj(kind, ns, name)
                if reasons is None or e.get("reason") in reasons]  # fmt: skip


def _any(texts: list[str], *needles: str) -> bool:
    low = " ".join(texts).lower()
    return any(n in low for n in needles)


# ---------------------------------------------------------------- pod analysis
def _pod_problem(pod: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Return (reason, container_status) of the most significant pod problem, if any."""
    st = pod.get("status") or {}
    phase = st.get("phase")
    statuses = (st.get("initContainerStatuses") or []) + (st.get("containerStatuses") or [])
    for cs in statuses:
        waiting = (cs.get("state") or {}).get("waiting") or {}
        last = (cs.get("lastState") or {}).get("terminated") or {}
        r = waiting.get("reason")
        if r == "CrashLoopBackOff" and last.get("reason") == "OOMKilled":
            return "OOMKilled", cs
        if r in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError",
                 "InvalidImageName", "CreateContainerError", "RunContainerError"):  # fmt: skip
            return ("ImagePullBackOff" if r in ("ErrImagePull", "InvalidImageName") else r), cs
    for cs in statuses:
        last = (cs.get("lastState") or {}).get("terminated") or {}
        term = (cs.get("state") or {}).get("terminated") or {}
        if term.get("reason") == "OOMKilled" or (last.get("reason") == "OOMKilled"
                                                  and (age_seconds(last.get("finishedAt")) or 1e9) < 6 * 3600):  # fmt: skip
            return "OOMKilled", cs
    if phase == "Failed":
        return "PodFailed", {}
    if phase == "Unknown" or st.get("reason") == "NodeLost":
        return "PodUnknown", {}
    if phase == "Pending":
        sched = condition(pod, "PodScheduled")
        age = age_seconds((pod.get("metadata") or {}).get("creationTimestamp")) or 0
        if (sched and sched.get("status") == "False") or age > 120:
            return "Pending", {}
    for cs in statuses:
        last = (cs.get("lastState") or {}).get("terminated") or {}
        if cs.get("restartCount", 0) >= 5 and last and (age_seconds(last.get("finishedAt")) or 1e9) < 3600:
            return "HighRestarts", cs
    return None


def _image_checks(image: str, msgs: list[str], pod: dict[str, Any]) -> tuple[list[Check], str | None]:
    info = parse_image(image)
    checks: list[Check] = []
    likely = None
    checks.append(Check("image_format", "ok" if info["valid"] else "fail", {"image": image}))
    if not info["valid"]:
        return checks, "image_format"
    tag = info.get("tag")
    if info.get("digest"):
        checks.append(Check("image_tag", "ok", {"tag": info["digest"][:19]}))
    elif not tag or tag == "latest":
        checks.append(Check("image_tag", "warn", {"tag": tag or "latest"}))
    not_found = _any(msgs, "not found", "manifest unknown", "does not exist", "no such image", "repository does not exist")
    checks.append(Check("tag_exists", "fail" if not_found else ("unknown" if not msgs else "ok"),
                        {"tag": tag or "latest"}))  # fmt: skip
    if not_found:
        likely = "tag_exists"
    unreachable = _any(msgs, "no such host", "i/o timeout", "connection refused", "network is unreachable",
                       "dial tcp", "tls: ", "x509", "context deadline exceeded")  # fmt: skip
    checks.append(Check("registry_reachable", "fail" if unreachable else ("unknown" if not msgs else "ok"),
                        {"registry": info["registry"]}))  # fmt: skip
    if unreachable and not likely:
        likely = "registry_reachable"
    auth_fail = _any(msgs, "unauthorized", "authentication required", "access denied", "denied:", "401", "403",
                     "insufficient_scope", "pull access denied")  # fmt: skip
    pull_secrets = [s.get("name") for s in (pod.get("spec") or {}).get("imagePullSecrets") or []]
    private = info["registry"] not in PUBLIC_REGISTRIES
    if auth_fail:
        status = "fail"
        likely = likely or "registry_auth"
    elif private and not pull_secrets:
        status = "warn"
    else:
        status = "unknown" if not msgs else "ok"
    checks.append(Check("registry_auth", status, {"registry": info["registry"], "pullSecrets": pull_secrets,
                                                  "private": private}))  # fmt: skip
    return checks, likely


def _crash_checks(cs: dict[str, Any], msgs: list[str]) -> tuple[list[Check], str | None, dict[str, Any]]:
    last = (cs.get("lastState") or {}).get("terminated") or {}
    code = last.get("exitCode")
    facts = {"exitCode": code, "exitMeaning": EXIT_CODES.get(code, "other") if code is not None else None,
             "lastReason": last.get("reason"), "lastFinishedAt": last.get("finishedAt"),
             "restarts": cs.get("restartCount", 0)}  # fmt: skip
    checks = [Check("exit_code", "unknown" if code is None else "fail",
                    {"exitCode": code, "meaning": facts["exitMeaning"]})]  # fmt: skip
    likely = "exit_code" if code is not None else None
    liveness = _any(msgs, "liveness probe failed")
    checks.append(Check("liveness_probe", "fail" if liveness else "ok"))
    if liveness:
        likely = "liveness_probe"
    oom = last.get("reason") == "OOMKilled"
    checks.append(Check("memory_limit", "fail" if oom else "ok"))
    if oom:
        likely = "memory_limit"
    return checks, likely, facts


def _container_spec(pod: dict[str, Any], name: str | None) -> dict[str, Any]:
    spec = pod.get("spec") or {}
    for c in (spec.get("initContainers") or []) + (spec.get("containers") or []):
        if c.get("name") == name:
            return c
    return {}


def _pod_requests(pod: dict[str, Any]) -> tuple[float, int]:
    cpu = 0.0
    mem = 0
    for c in (pod.get("spec") or {}).get("containers") or []:
        req = (c.get("resources") or {}).get("requests") or {}
        cpu += cpu_cores(req.get("cpu")) or 0
        mem += bytes_(req.get("memory")) or 0
    return cpu, mem


def _pending_checks(pod: dict[str, Any], msgs: list[str], nodes: list[dict[str, Any]],
                    pvcs: dict[tuple[str, str], dict[str, Any]]) -> tuple[list[Check], str | None]:  # fmt: skip
    sched = condition(pod, "PodScheduled") or {}
    text = [sched.get("message") or "", *msgs]
    checks: list[Check] = []
    likely = None
    cpu, mem = _pod_requests(pod)
    ready_nodes = [n for n in nodes if node_ready(n) and not (n.get("spec") or {}).get("unschedulable")]
    max_cpu = max((cpu_cores(((n.get("status") or {}).get("allocatable") or {}).get("cpu")) or 0 for n in ready_nodes),
                  default=0)  # fmt: skip
    max_mem = max((bytes_(((n.get("status") or {}).get("allocatable") or {}).get("memory")) or 0 for n in ready_nodes),
                  default=0)  # fmt: skip
    checks.append(Check("schedulable_nodes", "ok" if ready_nodes else "fail", {"count": len(ready_nodes)}))
    if not ready_nodes:
        likely = "schedulable_nodes"
    ins_cpu = _any(text, "insufficient cpu")
    ins_mem = _any(text, "insufficient memory")
    checks.append(Check("cpu_capacity", "fail" if ins_cpu or (cpu > max_cpu > 0) else "ok",
                        {"requested": cpu, "maxNode": max_cpu}))  # fmt: skip
    checks.append(Check("memory_capacity", "fail" if ins_mem or (mem > max_mem > 0) else "ok",
                        {"requested": mem, "maxNode": max_mem}))  # fmt: skip
    if ins_mem or mem > max_mem > 0:
        likely = likely or "memory_capacity"
    if ins_cpu or cpu > max_cpu > 0:
        likely = likely or "cpu_capacity"
    taints = _any(text, "untolerated taint", "had taint")
    checks.append(Check("taints", "warn" if taints else "ok"))
    affinity = _any(text, "didn't match pod's node affinity", "node(s) didn't match", "node selector")
    checks.append(Check("node_selector", "fail" if affinity else "ok"))
    if affinity:
        likely = likely or "node_selector"
    ns = (pod.get("metadata") or {}).get("namespace", "")
    unbound = []
    for v in (pod.get("spec") or {}).get("volumes") or []:
        claim = (v.get("persistentVolumeClaim") or {}).get("claimName")
        if claim:
            pvc = pvcs.get((ns, claim))
            if pvc is None or (pvc.get("status") or {}).get("phase") != "Bound":
                unbound.append(claim)
    pvc_issue = bool(unbound) or _any(text, "unbound immediate persistentvolumeclaims", "persistentvolumeclaim")
    checks.append(Check("volumes_bound", "fail" if pvc_issue else "ok", {"claims": unbound}))
    if pvc_issue:
        likely = likely or "volumes_bound"
    quota = _any(text, "exceeded quota", "forbidden: exceeded")
    if quota:
        checks.append(Check("quota", "fail"))
        likely = likely or "quota"
    return checks, likely


def _config_checks(pod: dict[str, Any], msgs: list[str], cs: dict[str, Any],
                   configmaps: set[tuple[str, str]], secrets: set[tuple[str, str]]) -> tuple[list[Check], str | None]:  # fmt: skip
    ns = (pod.get("metadata") or {}).get("namespace", "")
    c = _container_spec(pod, cs.get("name"))
    missing_cm, missing_sec = set(), set()
    refs_cm, refs_sec = set(), set()
    for ef in c.get("envFrom") or []:
        if ef.get("configMapRef") and not ef["configMapRef"].get("optional"):
            refs_cm.add(ef["configMapRef"]["name"])
        if ef.get("secretRef") and not ef["secretRef"].get("optional"):
            refs_sec.add(ef["secretRef"]["name"])
    for e in c.get("env") or []:
        vf = e.get("valueFrom") or {}
        if vf.get("configMapKeyRef") and not vf["configMapKeyRef"].get("optional"):
            refs_cm.add(vf["configMapKeyRef"]["name"])
        if vf.get("secretKeyRef") and not vf["secretKeyRef"].get("optional"):
            refs_sec.add(vf["secretKeyRef"]["name"])
    for v in (pod.get("spec") or {}).get("volumes") or []:
        if v.get("configMap") and not v["configMap"].get("optional"):
            refs_cm.add(v["configMap"]["name"])
        if v.get("secret") and not v["secret"].get("optional"):
            refs_sec.add(v["secret"]["secretName"])
    missing_cm = {n for n in refs_cm if (ns, n) not in configmaps}
    missing_sec = {n for n in refs_sec if (ns, n) not in secrets}
    checks = [Check("configmaps_exist", "fail" if missing_cm else "ok", {"missing": sorted(missing_cm)}),
              Check("secrets_exist", "fail" if missing_sec else "ok", {"missing": sorted(missing_sec)})]  # fmt: skip
    missing_key = _any(msgs + [((cs.get("state") or {}).get("waiting") or {}).get("message") or ""],
                       "couldn't find key")  # fmt: skip
    checks.append(Check("keys_exist", "fail" if missing_key else "ok"))
    likely = "configmaps_exist" if missing_cm else "secrets_exist" if missing_sec else "keys_exist" if missing_key else None
    return checks, likely


def analyze(snapshot: dict[str, list[dict[str, Any]]]) -> list[Issue]:
    """snapshot keys: nodes, pods, deployments, statefulsets, daemonsets, jobs, pvcs, events,
    storageclasses, configmaps, secrets (secrets: metadata only is enough), pod_metrics (optional)."""
    issues: list[Issue] = []
    events = _Events(snapshot.get("events") or [])
    nodes = snapshot.get("nodes") or []
    pvcs = {((p.get("metadata") or {}).get("namespace", ""), p["metadata"]["name"]): p
            for p in snapshot.get("pvcs") or []}  # fmt: skip
    cms = {((o.get("metadata") or {}).get("namespace", ""), o["metadata"]["name"]) for o in snapshot.get("configmaps") or []}
    secs = {((o.get("metadata") or {}).get("namespace", ""), o["metadata"]["name"]) for o in snapshot.get("secrets") or []}
    metrics = {((m.get("metadata") or {}).get("namespace"), m["metadata"]["name"]): m
               for m in snapshot.get("pod_metrics") or []}  # fmt: skip
    have_cm_data = "configmaps" in snapshot and "secrets" in snapshot

    # --- pods, grouped by (application, reason)
    groups: dict[tuple[str, str, str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for pod in snapshot.get("pods") or []:
        prob = _pod_problem(pod)
        if not prob:
            continue
        reason, cs = prob
        meta = pod.get("metadata") or {}
        owner = top_owner(pod)
        app = f"{owner['kind']}/{owner['name']}" if owner else f"Pod/{meta.get('name')}"
        groups[(meta.get("namespace", ""), app, reason, cs.get("name") or "")].append((pod, cs))

    for (ns, app, reason, cname), members in groups.items():
        pod, cs = members[0]
        meta = pod.get("metadata") or {}
        name = meta.get("name", "")
        owner = top_owner(pod)
        msgs = events.messages("Pod", ns, name)
        waiting = ((cs.get("state") or {}).get("waiting") or {}) if cs else {}
        issue = Issue(
            id=f"pod:{ns}:{app}:{reason}:{cname}", severity="ERROR", reason=reason, kind="Pod", name=name,
            namespace=ns, owner=owner, node=(pod.get("spec") or {}).get("nodeName"), container=cname or None,
            message=waiting.get("message") or (pod.get("status") or {}).get("message") or (msgs[0] if msgs else ""),
            since=meta.get("creationTimestamp"), affected=[m[0]["metadata"]["name"] for m in members],
            actions=["view_resource", "view_events", "view_yaml"],
        )  # fmt: skip
        issue.facts["status"] = pod_reason(pod)
        issue.facts["podCount"] = len(members)
        if reason == "ImagePullBackOff":
            image = cs.get("image") or _container_spec(pod, cname).get("image", "")
            issue.facts["image"] = image
            issue.checks, issue.likely_cause = _image_checks(image, msgs, pod)
            issue.actions += ["view_config", "check_registry"]
            issue.guide = "imagepullbackoff"
            issue.message = next((m for m in msgs if "pull" in m.lower() and m != "Error: ImagePullBackOff"),
                                 issue.message)  # fmt: skip
        elif reason == "CrashLoopBackOff" or reason == "HighRestarts":
            issue.checks, issue.likely_cause, facts = _crash_checks(cs, msgs)
            issue.facts.update(facts)
            issue.actions += ["view_logs", "view_previous_logs", "restart"]
            issue.guide = "crashloopbackoff"
            if reason == "HighRestarts":
                issue.severity = "WARNING"
        elif reason == "OOMKilled":
            c = _container_spec(pod, cs.get("name"))
            limit = ((c.get("resources") or {}).get("limits") or {}).get("memory")
            request = ((c.get("resources") or {}).get("requests") or {}).get("memory")
            usage = None
            m = metrics.get((ns, name))
            if m:
                for mc in m.get("containers") or []:
                    if mc.get("name") == cs.get("name"):
                        usage = bytes_((mc.get("usage") or {}).get("memory"))
            issue.facts.update({"memoryLimit": limit, "memoryRequest": request, "memoryUsage": usage,
                                "restarts": cs.get("restartCount", 0)})  # fmt: skip
            issue.checks = [
                Check("memory_limit_set", "ok" if limit else "warn", {"limit": limit}),
                Check("memory_usage", "unknown" if usage is None else (
                    "warn" if limit and usage > 0.8 * (bytes_(limit) or 1) else "ok"),
                    {"usage": usage, "limit": bytes_(limit) if limit else None}),
            ]  # fmt: skip
            issue.likely_cause = "memory_limit_set"
            running = bool((cs.get("state") or {}).get("running"))
            issue.severity = "WARNING" if running else "ERROR"
            issue.actions += ["view_logs", "view_previous_logs", "view_metrics", "restart"]
            issue.guide = "oomkilled"
        elif reason == "Pending":
            issue.checks, issue.likely_cause = _pending_checks(pod, msgs, nodes, pvcs)
            sched = condition(pod, "PodScheduled") or {}
            issue.message = sched.get("message") or issue.message
            issue.severity = "WARNING"
            issue.guide = "pending"
        elif reason == "CreateContainerConfigError":
            if have_cm_data:
                issue.checks, issue.likely_cause = _config_checks(pod, msgs, cs, cms, secs)
            issue.actions += ["view_config"]
            issue.guide = "createcontainerconfigerror"
        elif reason in ("PodFailed", "PodUnknown"):
            st = pod.get("status") or {}
            issue.facts.update({"phase": st.get("phase"), "statusReason": st.get("reason")})
            node = (pod.get("spec") or {}).get("nodeName")
            node_obj = next((n for n in nodes if n["metadata"]["name"] == node), None)
            if node_obj is not None:
                issue.checks.append(Check("node_ready", "ok" if node_ready(node_obj) else "fail", {"node": node}))
                if not node_ready(node_obj):
                    issue.likely_cause = "node_ready"
            issue.actions += ["view_logs"]
            issue.guide = "pod-failed-unknown"
            issue.severity = "ERROR" if reason == "PodFailed" else "WARNING"
        else:  # CreateContainerError / RunContainerError
            issue.actions += ["view_logs"]
            issue.guide = "troubleshooting"
        issue.actions.append("guide")
        issues.append(issue)

    # --- workloads
    for dep in snapshot.get("deployments") or []:
        meta, spec, st = dep.get("metadata") or {}, dep.get("spec") or {}, dep.get("status") or {}
        desired = spec.get("replicas", 1)
        avail = st.get("availableReplicas", 0) or 0
        ns, name = meta.get("namespace"), meta.get("name", "")
        owner = {"kind": "Deployment", "name": name}
        prog = condition(dep, "Progressing") or {}
        if spec.get("paused"):
            issues.append(Issue(id=f"deploy:{ns}:{name}:paused", severity="INFO", reason="DeploymentPaused",
                                kind="Deployment", name=name, namespace=ns, owner=owner,
                                actions=["view_resource", "resume"], guide="rolling-update"))  # fmt: skip
        if desired > 0 and avail == 0:
            sev, reason = "CRITICAL", "WorkloadUnavailable"
        elif desired > 0 and avail < desired:
            sev, reason = ("ERROR" if avail * 2 < desired else "WARNING"), "WorkloadDegraded"
        else:
            sev = reason = ""
        if prog.get("reason") == "ProgressDeadlineExceeded":
            sev, reason = sev or "ERROR", reason or "RolloutStuck"
        if reason:
            issues.append(Issue(
                id=f"deploy:{ns}:{name}:{reason}", severity=sev, reason=reason, kind="Deployment", name=name,
                namespace=ns, owner=owner,
                message=((condition(dep, "Available") or {}).get("message") if reason != "RolloutStuck" else None)
                or prog.get("message") or "",
                facts={"desired": desired, "available": avail, "ready": st.get("readyReplicas", 0) or 0,
                       "rolloutStuck": prog.get("reason") == "ProgressDeadlineExceeded"},
                actions=["view_resource", "view_pods", "view_events", "view_logs", "restart", "rollback", "guide"],
                guide="deployment"))  # fmt: skip
    for sts in snapshot.get("statefulsets") or []:
        meta, spec, st = sts.get("metadata") or {}, sts.get("spec") or {}, sts.get("status") or {}
        desired = spec.get("replicas", 1)
        ready = st.get("readyReplicas", 0) or 0
        if desired > 0 and ready < desired:
            issues.append(Issue(
                id=f"sts:{meta.get('namespace')}:{meta['name']}", severity="CRITICAL" if ready == 0 else "ERROR",
                reason="WorkloadUnavailable" if ready == 0 else "WorkloadDegraded", kind="StatefulSet",
                name=meta["name"], namespace=meta.get("namespace"), owner={"kind": "StatefulSet", "name": meta["name"]},
                facts={"desired": desired, "available": ready, "ready": ready},
                actions=["view_resource", "view_pods", "view_events", "guide"], guide="statefulset"))  # fmt: skip
    for ds in snapshot.get("daemonsets") or []:
        meta, st = ds.get("metadata") or {}, ds.get("status") or {}
        desired = st.get("desiredNumberScheduled", 0) or 0
        ready = st.get("numberReady", 0) or 0
        if desired > 0 and ready < desired:
            issues.append(Issue(
                id=f"ds:{meta.get('namespace')}:{meta['name']}", severity="WARNING" if ready else "ERROR",
                reason="WorkloadDegraded" if ready else "WorkloadUnavailable", kind="DaemonSet", name=meta["name"],
                namespace=meta.get("namespace"), owner={"kind": "DaemonSet", "name": meta["name"]},
                facts={"desired": desired, "available": ready, "ready": ready},
                actions=["view_resource", "view_pods", "view_events", "guide"], guide="daemonset"))  # fmt: skip
    for job in snapshot.get("jobs") or []:
        failed = condition(job, "Failed")
        if failed and failed.get("status") == "True" and (age_seconds(failed.get("lastTransitionTime")) or 0) < 86400 * 3:
            meta = job.get("metadata") or {}
            issues.append(Issue(
                id=f"job:{meta.get('namespace')}:{meta['name']}", severity="ERROR", reason="JobFailed", kind="Job",
                name=meta["name"], namespace=meta.get("namespace"), message=failed.get("message") or "",
                facts={"failReason": failed.get("reason"), "failed": (job.get("status") or {}).get("failed", 0)},
                actions=["view_resource", "view_pods", "view_events", "view_logs", "guide"], guide="job"))  # fmt: skip

    # --- nodes
    for node in nodes:
        meta = node.get("metadata") or {}
        name = meta.get("name", "")
        ready_c = condition(node, "Ready") or {}
        pods_on = [p for p in snapshot.get("pods") or [] if (p.get("spec") or {}).get("nodeName") == name]
        if not node_ready(node):
            hb = ready_c.get("lastHeartbeatTime")
            pressures = [c["type"] for c in (node.get("status") or {}).get("conditions") or []
                         if c.get("type") != "Ready" and c.get("status") == "True"]  # fmt: skip
            issues.append(Issue(
                id=f"node:{name}:notready", severity="CRITICAL", reason="NodeNotReady", kind="Node", name=name,
                namespace=None, node=name, message=ready_c.get("message") or "", since=ready_c.get("lastTransitionTime"),
                facts={"readyStatus": ready_c.get("status"), "readyReason": ready_c.get("reason"),
                       "lastHeartbeat": hb, "heartbeatAgeSeconds": age_seconds(hb), "podsOnNode": len(pods_on)},
                checks=[Check("kubelet_heartbeat", "fail" if (age_seconds(hb) or 0) > 60 else "ok",
                              {"ageSeconds": age_seconds(hb)}),
                        Check("node_pressure", "fail" if pressures else "ok", {"conditions": pressures})],
                likely_cause="kubelet_heartbeat" if (age_seconds(hb) or 0) > 60 else ("node_pressure" if pressures else None),
                actions=["view_resource", "view_events", "view_pods", "cordon", "guide"], guide="node-notready"))  # fmt: skip
            continue
        for c in (node.get("status") or {}).get("conditions") or []:
            if c.get("type") in ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable") and \
                    c.get("status") == "True":  # fmt: skip
                issues.append(Issue(
                    id=f"node:{name}:{c['type']}", severity="ERROR", reason="NodePressure", kind="Node", name=name,
                    namespace=None, node=name, message=c.get("message") or "", since=c.get("lastTransitionTime"),
                    facts={"condition": c["type"]}, actions=["view_resource", "view_events", "view_pods", "guide"],
                    guide="node"))  # fmt: skip
        if (node.get("spec") or {}).get("unschedulable"):
            issues.append(Issue(id=f"node:{name}:cordoned", severity="INFO", reason="NodeCordoned", kind="Node",
                                name=name, namespace=None, node=name, facts={"podsOnNode": len(pods_on)},
                                actions=["view_resource", "uncordon", "guide"], guide="proc-manutenzione-nodo"))  # fmt: skip

    # --- storage
    sc_names = {s["metadata"]["name"]: s for s in snapshot.get("storageclasses") or []}
    default_sc = next((n for n, s in sc_names.items() if ((s.get("metadata") or {}).get("annotations") or {}).get(
        "storageclass.kubernetes.io/is-default-class") == "true"), None)  # fmt: skip
    used_claims = {((p.get("metadata") or {}).get("namespace"), (v.get("persistentVolumeClaim") or {}).get("claimName"))
                   for p in snapshot.get("pods") or [] for v in (p.get("spec") or {}).get("volumes") or []
                   if v.get("persistentVolumeClaim")}  # fmt: skip
    for (ns, name), pvc in pvcs.items():
        phase = (pvc.get("status") or {}).get("phase")
        if phase not in ("Pending", "Lost"):
            continue
        if (age_seconds((pvc.get("metadata") or {}).get("creationTimestamp")) or 0) < 60 and phase == "Pending":
            continue
        sc = (pvc.get("spec") or {}).get("storageClassName") or default_sc
        sc_obj = sc_names.get(sc or "")
        msgs = events.messages("PersistentVolumeClaim", ns, name)
        wait_consumer = sc_obj is not None and sc_obj.get("volumeBindingMode") == "WaitForFirstConsumer" and \
            (ns, name) not in used_claims  # fmt: skip
        checks = [Check("storage_class_exists", "ok" if sc_obj else "fail", {"storageClass": sc})]
        if wait_consumer:
            checks.append(Check("waiting_first_consumer", "warn", {"storageClass": sc}))
        prov_failed = _any(msgs, "provisioningfailed", "failed to provision", "not found")
        checks.append(Check("provisioning", "fail" if prov_failed else "unknown" if not msgs else "ok"))
        issues.append(Issue(
            id=f"pvc:{ns}:{name}", severity="ERROR" if phase == "Lost" else ("INFO" if wait_consumer else "WARNING"),
            reason="PVCLost" if phase == "Lost" else "PVCPending", kind="PersistentVolumeClaim", name=name,
            namespace=ns, message=msgs[0] if msgs else "", since=(pvc.get("metadata") or {}).get("creationTimestamp"),
            facts={"storageClass": sc, "requested": (((pvc.get("spec") or {}).get("resources") or {}).get("requests") or {}).get("storage")},
            checks=checks, likely_cause="storage_class_exists" if not sc_obj else ("provisioning" if prov_failed else None),
            actions=["view_resource", "view_events", "view_yaml", "guide"], guide="persistent-volume-claim"))  # fmt: skip

    issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], i.namespace or "", i.kind, i.name))
    return issues


def summary_counts(issues: list[Issue]) -> dict[str, int]:
    counts = {k: 0 for k in SEVERITY_ORDER}
    for i in issues:
        counts[i.severity] += 1
    return counts
