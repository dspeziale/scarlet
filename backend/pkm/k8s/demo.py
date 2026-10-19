"""DEMO provider: an in-memory simulated cluster.

Used only when `mode: demo` (which is refused with environment=production).
Every API response carries the DEMO flag and the UI shows a permanent banner.
The data reproduces realistic situations (healthy apps, CrashLoopBackOff,
ImagePullBackOff, OOMKilled, Pending, NotReady node, Pending PVC) so that the
diagnostics and the UI can be exercised without a cluster.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import random
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from ..errors import K8sConflict, K8sInvalid, K8sNotFound
from .kinds import BY_KIND, KINDS
from .provider import KubernetesProvider, LogStream

VERSION = {"gitVersion": "v1.31.4-demo", "major": "1", "minor": "31", "platform": "linux/amd64"}


def _ts(delta: timedelta) -> str:
    return (datetime.now(UTC) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uid() -> str:
    return str(uuid.uuid4())


def _hash(text: str, n: int = 9) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:n]


def _meta(name: str, namespace: str | None = None, *, age: timedelta = timedelta(days=12),
          labels: dict[str, str] | None = None, owner: dict[str, Any] | None = None,
          annotations: dict[str, str] | None = None) -> dict[str, Any]:  # fmt: skip
    m: dict[str, Any] = {"name": name, "uid": _uid(), "creationTimestamp": _ts(age), "resourceVersion": "1"}
    if namespace:
        m["namespace"] = namespace
    if labels:
        m["labels"] = labels
    if annotations:
        m["annotations"] = annotations
    if owner:
        m["ownerReferences"] = [{**owner, "controller": True, "blockOwnerDeletion": True}]
    return m


def _container(name: str, image: str, port: int | None = None, *, cpu: str = "100m", mem: str = "128Mi",
               cpu_lim: str | None = "500m", mem_lim: str | None = "256Mi", probes: bool = True) -> dict[str, Any]:  # fmt: skip
    c: dict[str, Any] = {"name": name, "image": image, "imagePullPolicy": "IfNotPresent"}
    if port:
        c["ports"] = [{"containerPort": port, "protocol": "TCP", "name": "http"}]
    res: dict[str, Any] = {"requests": {"cpu": cpu, "memory": mem}}
    limits = {k: v for k, v in (("cpu", cpu_lim), ("memory", mem_lim)) if v}
    if limits:
        res["limits"] = limits
    c["resources"] = res
    if probes and port:
        c["readinessProbe"] = {"httpGet": {"path": "/healthz", "port": port}, "periodSeconds": 10}
        c["livenessProbe"] = {"httpGet": {"path": "/healthz", "port": port}, "initialDelaySeconds": 15,
                              "periodSeconds": 20}  # fmt: skip
    return c


class DemoKubernetes(KubernetesProvider):
    demo = True

    def __init__(self, seed: int = 42) -> None:
        self._lock = threading.RLock()
        self._rv = itertools.count(1000)
        self._store: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._rand = random.Random(seed)
        self._build()

    # ------------------------------------------------------------------ storage
    def _key(self, kind: str, name: str, ns: str | None) -> tuple[str, str, str]:
        info = BY_KIND[kind]
        return (kind, (ns or "") if info.namespaced else "", name)

    def _put(self, obj: dict[str, Any]) -> dict[str, Any]:
        info = BY_KIND[obj["kind"]]
        obj.setdefault("apiVersion", info.api_version)
        meta = obj["metadata"]
        meta["resourceVersion"] = str(next(self._rv))
        meta.setdefault("uid", _uid())
        meta.setdefault("creationTimestamp", _ts(timedelta(0)))
        self._store[self._key(obj["kind"], meta["name"], meta.get("namespace"))] = obj
        return obj

    # ------------------------------------------------------------------ fixtures
    def _build(self) -> None:
        for name, role, ready, cpu, mem in (
            ("node-01", "control-plane", True, "4", "16Gi"),
            ("node-02", "worker", True, "8", "32Gi"),
            ("node-03", "worker", False, "8", "32Gi"),
        ):
            self._put(self._node(name, role, ready, cpu, mem))
        for ns in ("default", "kube-system", "production", "staging", "monitoring"):
            self._put({"kind": "Namespace", "metadata": _meta(ns, age=timedelta(days=90),
                       labels={"kubernetes.io/metadata.name": ns}), "spec": {"finalizers": ["kubernetes"]},
                       "status": {"phase": "Active"}})  # fmt: skip
        self._put({"kind": "StorageClass", "metadata": _meta("standard", age=timedelta(days=90), annotations={
            "storageclass.kubernetes.io/is-default-class": "true"}), "provisioner": "rancher.io/local-path",
            "reclaimPolicy": "Delete", "volumeBindingMode": "WaitForFirstConsumer"})  # fmt: skip

        # production
        self._deployment("production", "web-prod", "nginx:1.27.2", 3, port=80, history=["nginx:1.25.4"])
        self._deployment("production", "api-prod", "registry.example.com/shop/api:2.4.1", 2, port=8080,
                         broken={"index": 1, "type": "crash"})  # fmt: skip
        self._deployment("production", "worker-prod", "registry.example.com/shop/worker:2.5.0-rc1", 2,
                         broken={"index": "all", "type": "imagepull"})  # fmt: skip
        self._statefulset("production", "redis", "redis:7.4.1", port=6379)
        self._service("production", "web-prod", 80, {"app": "web-prod"})
        self._service("production", "api-prod", 8080, {"app": "api-prod"})
        self._service("production", "redis", 6379, {"app": "redis"}, headless=True)
        self._put({"kind": "Ingress", "metadata": _meta("shop", "production"), "spec": {
            "ingressClassName": "nginx",
            "tls": [{"hosts": ["shop.example.com"], "secretName": "shop-tls"}],
            "rules": [{"host": "shop.example.com", "http": {"paths": [
                {"path": "/", "pathType": "Prefix", "backend": {"service": {"name": "web-prod", "port": {"number": 80}}}},
                {"path": "/api", "pathType": "Prefix", "backend": {"service": {"name": "api-prod", "port": {"number": 8080}}}},
            ]}}]}, "status": {"loadBalancer": {"ingress": [{"ip": "192.168.10.50"}]}}})  # fmt: skip
        self._put({"kind": "ConfigMap", "metadata": _meta("web-config", "production"),
                   "data": {"nginx.conf": "server {\n  listen 80;\n  location / { root /usr/share/nginx/html; }\n}\n",
                            "FEATURE_FLAGS": "checkout-v2=true"}})  # fmt: skip
        self._put({"kind": "Secret", "metadata": _meta("api-credentials", "production"), "type": "Opaque",
                   "data": {"DB_USER": "c2hvcA==", "DB_PASSWORD": "ZGVtby1ub3QtYS1yZWFsLXNlY3JldA=="}})  # fmt: skip
        self._put({"kind": "Secret", "metadata": _meta("shop-tls", "production"), "type": "kubernetes.io/tls",
                   "data": {"tls.crt": "LS0tLS1CRUdJTi1ERU1PLS0tLS0=", "tls.key": "LS0tLS1ERU1PLUtFWS0tLS0t"}})  # fmt: skip
        self._put({"kind": "PodDisruptionBudget", "metadata": _meta("web-prod", "production"),
                   "spec": {"minAvailable": 2, "selector": {"matchLabels": {"app": "web-prod"}}},
                   "status": {"currentHealthy": 3, "desiredHealthy": 2, "disruptionsAllowed": 1, "expectedPods": 3}})  # fmt: skip
        self._cronjob("production", "db-backup", "0 2 * * *")

        # staging
        self._deployment("staging", "web-staging", "nginx:1.27.2", 1, port=80, broken={"index": 0, "type": "oom"})
        self._deployment("staging", "reports-staging", "registry.example.com/shop/reports:1.8.0", 1, port=8080,
                         broken={"index": "all", "type": "pending"}, mem="24Gi", mem_lim="24Gi")  # fmt: skip
        self._put({"kind": "PersistentVolumeClaim", "metadata": _meta("uploads-staging", "staging", age=timedelta(hours=3)),
                   "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "fast-ssd",
                            "resources": {"requests": {"storage": "20Gi"}}, "volumeMode": "Filesystem"},
                   "status": {"phase": "Pending"}})  # fmt: skip

        # system
        self._deployment("kube-system", "coredns", "registry.k8s.io/coredns/coredns:v1.11.3", 2, port=53, probes=False,
                         labels={"k8s-app": "kube-dns"})  # fmt: skip
        self._service("kube-system", "kube-dns", 53, {"k8s-app": "kube-dns"})
        self._daemonset("kube-system", "kube-proxy", "registry.k8s.io/kube-proxy:v1.31.4")
        self._daemonset("monitoring", "node-exporter", "quay.io/prometheus/node-exporter:v1.8.2", port=9100)
        self._deployment("monitoring", "metrics-server", "registry.k8s.io/metrics-server/metrics-server:v0.7.2", 1,
                         port=10250, labels={"k8s-app": "metrics-server"})  # fmt: skip
        self._events()

    def _node(self, name: str, role: str, ready: bool, cpu: str, mem: str) -> dict[str, Any]:
        hb = timedelta(seconds=20) if ready else timedelta(minutes=47)
        conds = [
            {"type": "MemoryPressure", "status": "False", "reason": "KubeletHasSufficientMemory"},
            {"type": "DiskPressure", "status": "False", "reason": "KubeletHasNoDiskPressure"},
            {"type": "PIDPressure", "status": "False", "reason": "KubeletHasSufficientPID"},
            {"type": "Ready", "status": "True" if ready else "Unknown",
             "reason": "KubeletReady" if ready else "NodeStatusUnknown",
             "message": "kubelet is posting ready status" if ready else "Kubelet stopped posting node status."},
        ]  # fmt: skip
        for c in conds:
            c["lastHeartbeatTime"] = _ts(hb)
            c["lastTransitionTime"] = _ts(timedelta(days=30) if ready else timedelta(minutes=46))
        labels = {"kubernetes.io/hostname": name, "kubernetes.io/os": "linux", "kubernetes.io/arch": "amd64",
                  f"node-role.kubernetes.io/{role}": ""}  # fmt: skip
        spec: dict[str, Any] = {"podCIDR": f"10.244.{name[-1]}.0/24"}
        if role == "control-plane":
            spec["taints"] = [{"key": "node-role.kubernetes.io/control-plane", "effect": "NoSchedule"}]
        if not ready:
            spec["taints"] = [{"key": "node.kubernetes.io/unreachable", "effect": "NoExecute"},
                              {"key": "node.kubernetes.io/unreachable", "effect": "NoSchedule"}]  # fmt: skip
        return {
            "kind": "Node",
            "metadata": _meta(name, age=timedelta(days=120), labels=labels),
            "spec": spec,
            "status": {
                "capacity": {"cpu": cpu, "memory": mem, "pods": "110", "ephemeral-storage": "102350Mi"},
                "allocatable": {"cpu": cpu, "memory": mem, "pods": "110", "ephemeral-storage": "94000Mi"},
                "conditions": conds,
                "addresses": [{"type": "InternalIP", "address": f"192.168.10.{10 + int(name[-1])}"},
                              {"type": "Hostname", "address": name}],  # fmt: skip
                "nodeInfo": {"kubeletVersion": "v1.31.4", "osImage": "Oracle Linux Server 9.7",
                             "kernelVersion": "5.15.0-310.184.5.2.el9uek.x86_64",
                             "containerRuntimeVersion": "cri-o://1.31.3", "architecture": "amd64",
                             "operatingSystem": "linux"},  # fmt: skip
            },
        }

    def _pod_status(self, containers: list[dict[str, Any]], node: str, broken: str | None,
                    age: timedelta) -> tuple[dict[str, Any], str | None]:  # fmt: skip
        started = _ts(age)
        statuses = []
        phase, ready_all, assigned = "Running", True, node
        for c in containers:
            st: dict[str, Any] = {"name": c["name"], "image": c["image"], "imageID": "", "restartCount": 0,
                                  "ready": True, "started": True, "state": {"running": {"startedAt": started}}}  # fmt: skip
            if broken == "crash":
                st.update(ready=False, started=False, restartCount=14,
                          state={"waiting": {"reason": "CrashLoopBackOff",
                                             "message": f"back-off 5m0s restarting failed container={c['name']}"}},
                          lastState={"terminated": {"exitCode": 1, "reason": "Error", "startedAt": _ts(timedelta(minutes=6)),
                                                    "finishedAt": _ts(timedelta(minutes=5))}})  # fmt: skip
                ready_all = False
            elif broken == "imagepull":
                st.update(ready=False, started=False, imageID="",
                          state={"waiting": {"reason": "ImagePullBackOff",
                                             "message": f'Back-off pulling image "{c["image"]}"'}})  # fmt: skip
                ready_all = False
                phase = "Pending"
            elif broken == "oom":
                st.update(restartCount=3, state={"running": {"startedAt": _ts(timedelta(minutes=12))}},
                          lastState={"terminated": {"exitCode": 137, "reason": "OOMKilled",
                                                    "startedAt": _ts(timedelta(hours=2)),
                                                    "finishedAt": _ts(timedelta(minutes=12))}})  # fmt: skip
            elif broken == "pending":
                statuses = []
                phase, ready_all, assigned = "Pending", False, None
                break
            statuses.append(st)
        status: dict[str, Any] = {"phase": phase, "qosClass": "Burstable", "startTime": started}
        if assigned:
            status.update(hostIP=f"192.168.10.{10 + int(node[-1])}",
                          podIP=f"10.244.{node[-1]}.{self._rand.randint(2, 250)}",
                          containerStatuses=statuses)  # fmt: skip
        conds = [{"type": "PodScheduled", "status": "True" if assigned else "False"}]
        if not assigned:
            conds[0].update(reason="Unschedulable", message="0/3 nodes are available: 1 node(s) had untolerated "
                            "taint {node-role.kubernetes.io/control-plane: }, 1 node(s) had untolerated taint "
                            "{node.kubernetes.io/unreachable: }, 1 Insufficient memory. preemption: 0/3 nodes are "
                            "available: 1 No preemption victims found for incoming pod, 2 Preemption is not "
                            "helpful for scheduling.")  # fmt: skip
        else:
            conds += [{"type": "Initialized", "status": "True"},
                      {"type": "ContainersReady", "status": "True" if ready_all else "False"},
                      {"type": "Ready", "status": "True" if ready_all else "False"}]  # fmt: skip
        for cd in conds:
            cd["lastTransitionTime"] = started
        status["conditions"] = conds
        return status, assigned

    def _make_pod(self, ns: str, name: str, labels: dict[str, str], spec: dict[str, Any], owner: dict[str, Any],
                  node: str, broken: str | None, age: timedelta) -> dict[str, Any]:  # fmt: skip
        status, assigned = self._pod_status(spec["containers"], node, broken, age)
        pod_spec = copy.deepcopy(spec)
        if assigned:
            pod_spec["nodeName"] = assigned
        pod_spec.setdefault("restartPolicy", "Always")
        pod_spec.setdefault("serviceAccountName", "default")
        return {"kind": "Pod", "metadata": _meta(name, ns, age=age, labels=labels, owner=owner),
                "spec": pod_spec, "status": status}  # fmt: skip

    def _deployment(self, ns: str, name: str, image: str, replicas: int, *, port: int | None = None,
                    broken: dict[str, Any] | None = None, history: list[str] | None = None, probes: bool = True,
                    labels: dict[str, str] | None = None, mem: str = "128Mi", mem_lim: str = "256Mi") -> None:  # fmt: skip
        labels = labels or {"app": name}
        container = _container(name.split("-")[0], image, port, probes=probes, mem=mem, mem_lim=mem_lim)
        template = {"metadata": {"labels": dict(labels)}, "spec": {"containers": [container]}}
        if name == "api-prod":
            container["envFrom"] = [{"secretRef": {"name": "api-credentials"}}]
        if name == "web-prod":
            template["spec"]["volumes"] = [{"name": "config", "configMap": {"name": "web-config"}}]
            container["volumeMounts"] = [{"name": "config", "mountPath": "/etc/nginx/conf.d"}]
        revision = 1 + len(history or [])
        dep = {
            "kind": "Deployment",
            "metadata": _meta(name, ns, labels=dict(labels),
                              annotations={"deployment.kubernetes.io/revision": str(revision)}),  # fmt: skip
            "spec": {"replicas": replicas, "selector": {"matchLabels": dict(labels)}, "template": template,
                     "strategy": {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": "25%", "maxSurge": "25%"}},
                     "revisionHistoryLimit": 10, "progressDeadlineSeconds": 600},  # fmt: skip
        }
        dep = self._put(dep)
        for i, old_image in enumerate(history or [], start=1):
            old_t = copy.deepcopy(template)
            old_t["spec"]["containers"][0]["image"] = old_image
            self._replicaset(dep, old_t, i, 0, age=timedelta(days=20 - i))
        rs = self._replicaset(dep, template, revision, replicas, age=timedelta(days=2))
        nodes = ["node-02", "node-01"]
        for i in range(replicas):
            b = None
            if broken and (broken["index"] == "all" or broken["index"] == i):
                b = broken["type"]
            pod_name = f"{rs['metadata']['name']}-{_hash(name + str(i), 5)}"
            pod_labels = {**labels, "pod-template-hash": rs["metadata"]["labels"]["pod-template-hash"]}
            self._put(self._make_pod(ns, pod_name, pod_labels, template["spec"], self._ownerref(rs), nodes[i % 2], b,
                                     timedelta(days=2)))  # fmt: skip
        self._sync_workload_status(dep)

    def _ownerref(self, obj: dict[str, Any]) -> dict[str, Any]:
        return {"apiVersion": obj["apiVersion"], "kind": obj["kind"], "name": obj["metadata"]["name"],
                "uid": obj["metadata"]["uid"]}  # fmt: skip

    def _replicaset(self, dep: dict[str, Any], template: dict[str, Any], revision: int, replicas: int,
                    age: timedelta) -> dict[str, Any]:  # fmt: skip
        h = _hash(str(template), 10)
        labels = {**template["metadata"]["labels"], "pod-template-hash": h}
        t = copy.deepcopy(template)
        t["metadata"]["labels"] = labels
        rs = {"kind": "ReplicaSet",
              "metadata": _meta(f"{dep['metadata']['name']}-{h}", dep["metadata"]["namespace"], age=age, labels=labels,
                                owner=self._ownerref(dep),
                                annotations={"deployment.kubernetes.io/revision": str(revision)}),
              "spec": {"replicas": replicas, "selector": {"matchLabels": labels}, "template": t},
              "status": {"replicas": replicas, "readyReplicas": replicas, "availableReplicas": replicas,
                         "observedGeneration": 1}}  # fmt: skip
        return self._put(rs)

    def _statefulset(self, ns: str, name: str, image: str, port: int) -> None:
        labels = {"app": name}
        c = _container(name, image, port, probes=False, mem="256Mi", mem_lim="512Mi")
        c["volumeMounts"] = [{"name": "data", "mountPath": "/data"}]
        sts = self._put({"kind": "StatefulSet", "metadata": _meta(name, ns, labels=labels),
                         "spec": {"replicas": 1, "serviceName": name, "selector": {"matchLabels": labels},
                                  "template": {"metadata": {"labels": labels}, "spec": {"containers": [c]}},
                                  "volumeClaimTemplates": [{"metadata": {"name": "data"}, "spec": {
                                      "accessModes": ["ReadWriteOnce"], "storageClassName": "standard",
                                      "resources": {"requests": {"storage": "5Gi"}}}}]}})  # fmt: skip
        pvc_name = f"data-{name}-0"
        pv_name = f"pvc-{_hash(pvc_name, 8)}-demo"
        self._put({"kind": "PersistentVolume", "metadata": _meta(pv_name, labels={}), "spec": {
            "capacity": {"storage": "5Gi"}, "accessModes": ["ReadWriteOnce"], "persistentVolumeReclaimPolicy": "Delete",
            "storageClassName": "standard", "hostPath": {"path": f"/var/lib/local-path/{pv_name}"},
            "claimRef": {"kind": "PersistentVolumeClaim", "namespace": ns, "name": pvc_name}},
            "status": {"phase": "Bound"}})  # fmt: skip
        self._put({"kind": "PersistentVolumeClaim", "metadata": _meta(pvc_name, ns, labels=labels), "spec": {
            "accessModes": ["ReadWriteOnce"], "storageClassName": "standard", "volumeName": pv_name,
            "resources": {"requests": {"storage": "5Gi"}}, "volumeMode": "Filesystem"},
            "status": {"phase": "Bound", "capacity": {"storage": "5Gi"}, "accessModes": ["ReadWriteOnce"]}})  # fmt: skip
        spec = copy.deepcopy(sts["spec"]["template"]["spec"])
        spec["volumes"] = [{"name": "data", "persistentVolumeClaim": {"claimName": pvc_name}}]
        self._put(self._make_pod(ns, f"{name}-0", {**labels, "statefulset.kubernetes.io/pod-name": f"{name}-0"}, spec,
                                 self._ownerref(sts), "node-02", None, timedelta(days=12)))  # fmt: skip
        self._sync_workload_status(sts)

    def _daemonset(self, ns: str, name: str, image: str, port: int | None = None) -> None:
        labels = {"app": name}
        c = _container(name, image, port, probes=False, cpu="50m", mem="64Mi", cpu_lim=None, mem_lim="128Mi")
        ds = self._put({"kind": "DaemonSet", "metadata": _meta(name, ns, age=timedelta(days=120), labels=labels),
                        "spec": {"selector": {"matchLabels": labels},
                                 "template": {"metadata": {"labels": labels}, "spec": {
                                     "containers": [c], "tolerations": [{"operator": "Exists"}]}},
                                 "updateStrategy": {"type": "RollingUpdate"}}})  # fmt: skip
        for node in ("node-01", "node-02", "node-03"):
            pod = self._make_pod(ns, f"{name}-{_hash(name + node, 5)}", dict(labels), ds["spec"]["template"]["spec"],
                                 self._ownerref(ds), node, None, timedelta(days=120))  # fmt: skip
            if node == "node-03":
                pod["status"]["phase"] = "Unknown"
                pod["status"]["reason"] = "NodeLost"
                pod["status"]["message"] = "Node node-03 which was running pod is unresponsive"
                for cs in pod["status"].get("containerStatuses", []):
                    cs["ready"] = False
                for cd in pod["status"]["conditions"]:
                    if cd["type"] in ("Ready", "ContainersReady"):
                        cd["status"] = "False"
            self._put(pod)
        self._sync_workload_status(ds)

    def _service(self, ns: str, name: str, port: int, selector: dict[str, str], headless: bool = False) -> None:
        svc = {"kind": "Service", "metadata": _meta(name, ns, labels=dict(selector)), "spec": {
            "type": "ClusterIP", "selector": selector, "clusterIP": "None" if headless else f"10.96.{port % 250}.{len(name) * 7 % 250}",
            "ports": [{"name": "main", "port": port, "targetPort": port, "protocol": "TCP"}]}}  # fmt: skip
        self._put(svc)
        self._sync_endpoints(ns, name)

    def _cronjob(self, ns: str, name: str, schedule: str) -> None:
        tmpl = {"spec": {"backoffLimit": 2, "template": {"spec": {"restartPolicy": "OnFailure", "containers": [
            _container("backup", "registry.example.com/tools/pg-backup:16", probes=False)]}}}}  # fmt: skip
        cj = self._put({"kind": "CronJob", "metadata": _meta(name, ns),
                        "spec": {"schedule": schedule, "suspend": False, "concurrencyPolicy": "Forbid",
                                 "successfulJobsHistoryLimit": 3, "failedJobsHistoryLimit": 1, "jobTemplate": tmpl},
                        "status": {"lastScheduleTime": _ts(timedelta(hours=7)),
                                   "lastSuccessfulTime": _ts(timedelta(hours=6, minutes=58))}})  # fmt: skip
        job_name = f"{name}-{int(time.time() // 86400) * 1440}"
        job = self._put({"kind": "Job", "metadata": _meta(job_name, ns, age=timedelta(hours=7), labels={"job-name": job_name},
                                                         owner=self._ownerref(cj)),
                         "spec": {**copy.deepcopy(tmpl["spec"]), "completions": 1, "parallelism": 1},
                         "status": {"succeeded": 1, "startTime": _ts(timedelta(hours=7)),
                                    "completionTime": _ts(timedelta(hours=6, minutes=58)),
                                    "conditions": [{"type": "Complete", "status": "True"}]}})  # fmt: skip
        pod = self._make_pod(ns, f"{job_name}-{_hash(job_name, 5)}", {"job-name": job_name},
                             tmpl["spec"]["template"]["spec"], self._ownerref(job), "node-02", None,
                             timedelta(hours=7))  # fmt: skip
        pod["status"]["phase"] = "Succeeded"
        for cs in pod["status"]["containerStatuses"]:
            cs.update(ready=False, state={"terminated": {"exitCode": 0, "reason": "Completed",
                                                         "finishedAt": _ts(timedelta(hours=6, minutes=58))}})  # fmt: skip
        self._put(pod)

    def _events(self) -> None:
        pods = {o["metadata"]["name"]: o for (k, _, _), o in self._store.items() if k == "Pod"}

        def ev(ns: str, kind: str, name: str, etype: str, reason: str, msg: str, ago: timedelta, count: int = 1,
               source: str = "kubelet") -> None:  # fmt: skip
            ename = f"{name}.{_hash(reason + msg, 16)}"
            self._put({"kind": "Event", "metadata": _meta(ename, ns, age=ago),
                       "involvedObject": {"kind": kind, "namespace": ns, "name": name,
                                          "apiVersion": BY_KIND[kind].api_version},
                       "type": etype, "reason": reason, "message": msg, "count": count,
                       "firstTimestamp": _ts(ago + timedelta(minutes=30)), "lastTimestamp": _ts(ago),
                       "source": {"component": source}})  # fmt: skip

        for pname, pod in pods.items():
            ns = pod["metadata"]["namespace"]
            for cs in pod["status"].get("containerStatuses", []):
                waiting = (cs.get("state") or {}).get("waiting") or {}
                if waiting.get("reason") == "CrashLoopBackOff":
                    ev(ns, "Pod", pname, "Warning", "BackOff", "Back-off restarting failed container "
                       f"{cs['name']} in pod {pname}", timedelta(minutes=1), 58)  # fmt: skip
                if waiting.get("reason") == "ImagePullBackOff":
                    ev(ns, "Pod", pname, "Warning", "Failed", f'Failed to pull image "{cs["image"]}": rpc error: '
                       f'code = NotFound desc = failed to pull and unpack image "{cs["image"]}": failed to resolve '
                       f'reference "{cs["image"]}": {cs["image"]}: not found', timedelta(minutes=2), 31)  # fmt: skip
                    ev(ns, "Pod", pname, "Warning", "Failed", "Error: ImagePullBackOff", timedelta(minutes=2), 120)
                last = (cs.get("lastState") or {}).get("terminated") or {}
                if last.get("reason") == "OOMKilled":
                    ev(ns, "Pod", pname, "Warning", "BackOff", f"Back-off restarting failed container {cs['name']}",
                       timedelta(minutes=12), 3)  # fmt: skip
            if pod["status"]["phase"] == "Pending" and not pod["spec"].get("nodeName"):
                cond = pod["status"]["conditions"][0]
                ev(ns, "Pod", pname, "Warning", "FailedScheduling", cond["message"], timedelta(minutes=3), 17,
                   "default-scheduler")  # fmt: skip
        ev("default", "Node", "node-03", "Normal", "NodeNotReady", "Node node-03 status is now: NodeNotReady",
           timedelta(minutes=46), 1, "node-controller")  # fmt: skip
        ev("staging", "PersistentVolumeClaim", "uploads-staging", "Warning", "ProvisioningFailed",
           'storageclass.storage.k8s.io "fast-ssd" not found', timedelta(minutes=4), 12,
           "persistentvolume-controller")  # fmt: skip
        ev("production", "Deployment", "web-prod", "Normal", "ScalingReplicaSet",
           "Scaled up replica set web-prod to 3", timedelta(days=2), 1, "deployment-controller")  # fmt: skip

    # ------------------------------------------------------------------ simulation
    def _pods_for(self, ns: str, selector: dict[str, str]) -> list[dict[str, Any]]:
        out = []
        for (k, pns, _), o in self._store.items():
            if k == "Pod" and pns == ns:
                labels = o["metadata"].get("labels") or {}
                if selector and all(labels.get(a) == b for a, b in selector.items()):
                    out.append(o)
        return out

    def _sync_endpoints(self, ns: str, name: str) -> None:
        svc = self._store.get(("Service", ns, name))
        if not svc:
            return
        selector = svc["spec"].get("selector") or {}
        ready, not_ready = [], []
        for p in self._pods_for(ns, selector):
            ip = p["status"].get("podIP")
            if not ip:
                continue
            addr = {"ip": ip, "nodeName": p["spec"].get("nodeName"),
                    "targetRef": {"kind": "Pod", "name": p["metadata"]["name"], "namespace": ns}}  # fmt: skip
            is_ready = any(c["type"] == "Ready" and c["status"] == "True" for c in p["status"].get("conditions", []))
            (ready if is_ready else not_ready).append(addr)
        subset: dict[str, Any] = {"ports": [{"name": p.get("name"), "port": p.get("targetPort"), "protocol": "TCP"}
                                            for p in svc["spec"].get("ports", [])]}  # fmt: skip
        if ready:
            subset["addresses"] = ready
        if not_ready:
            subset["notReadyAddresses"] = not_ready
        self._put({"kind": "Endpoints", "metadata": _meta(name, ns, labels=svc["metadata"].get("labels")),
                   "subsets": [subset] if (ready or not_ready) else []})  # fmt: skip

    def _sync_workload_status(self, obj: dict[str, Any]) -> None:
        ns = obj["metadata"]["namespace"]
        selector = (obj["spec"].get("selector") or {}).get("matchLabels") or {}
        pods = [p for p in self._pods_for(ns, selector) if p["status"]["phase"] not in ("Succeeded", "Failed")]
        ready = [p for p in pods if any(c["type"] == "Ready" and c["status"] == "True"
                                        for c in p["status"].get("conditions", []))]  # fmt: skip
        gen = obj["metadata"].get("generation", 1)
        obj["metadata"]["generation"] = gen
        if obj["kind"] == "DaemonSet":
            obj["status"] = {"desiredNumberScheduled": len(pods), "currentNumberScheduled": len(pods),
                             "numberReady": len(ready), "numberAvailable": len(ready), "updatedNumberScheduled": len(pods),
                             "numberUnavailable": len(pods) - len(ready), "numberMisscheduled": 0,
                             "observedGeneration": gen}  # fmt: skip
            return
        desired = obj["spec"].get("replicas", 1)
        status: dict[str, Any] = {"replicas": len(pods), "readyReplicas": len(ready), "availableReplicas": len(ready),
                                  "updatedReplicas": len(pods), "observedGeneration": gen}  # fmt: skip
        if obj["kind"] == "Deployment":
            status["unavailableReplicas"] = max(0, desired - len(ready))
            avail = len(ready) >= desired - max(0, int(desired * 0.25))
            conds = [{"type": "Available", "status": "True" if (avail and len(ready) > 0) or desired == 0 else "False",
                      "reason": "MinimumReplicasAvailable" if avail else "MinimumReplicasUnavailable",
                      "message": "Deployment has minimum availability." if avail
                      else "Deployment does not have minimum availability."},
                     {"type": "Progressing", "status": "True", "reason": "NewReplicaSetAvailable"
                      if len(ready) == desired else "ReplicaSetUpdated", "message": "ReplicaSet is progressing."}]  # fmt: skip
            for c in conds:
                c["lastUpdateTime"] = c["lastTransitionTime"] = _ts(timedelta(hours=1))
            status["conditions"] = conds
        if obj["kind"] == "StatefulSet":
            status["currentReplicas"] = len(pods)
        obj["status"] = status
        for svc_key in [k for k in self._store if k[0] == "Service" and k[1] == ns]:
            self._sync_endpoints(ns, svc_key[2])

    def _reconcile_deployment(self, dep: dict[str, Any], *, restart: bool = False) -> None:
        ns, name = dep["metadata"]["namespace"], dep["metadata"]["name"]
        template = dep["spec"]["template"]
        rs_list = [o for (k, n, _), o in self._store.items() if k == "ReplicaSet" and n == ns and
                   any(r.get("uid") == dep["metadata"]["uid"] for r in o["metadata"].get("ownerReferences", []))]  # fmt: skip
        active = next((r for r in rs_list if r["spec"].get("replicas", 0) > 0), None)
        clean = copy.deepcopy(template)
        clean.get("metadata", {}).get("labels", {}).pop("pod-template-hash", None)
        h = None
        for rs in rs_list:
            t = copy.deepcopy(rs["spec"]["template"])
            t.get("metadata", {}).get("labels", {}).pop("pod-template-hash", None)
            if t == clean:
                h = rs["metadata"]["labels"].get("pod-template-hash")
        h = h or _hash(str(clean), 10)
        current = next((r for r in rs_list if r["metadata"]["labels"].get("pod-template-hash") == h), None)
        revisions = [int(r["metadata"].get("annotations", {}).get("deployment.kubernetes.io/revision", "0"))
                     for r in rs_list] or [0]  # fmt: skip
        # Scaling up from zero reuses the current ReplicaSet: only a template change is a rollout.
        rollout = restart or current is None or (active is not None and current is not active)
        if current is None:
            labels = {**(clean["metadata"].get("labels") or {}), "pod-template-hash": h}
            t = copy.deepcopy(clean)
            t["metadata"]["labels"] = labels
            current = self._put({"kind": "ReplicaSet", "metadata": _meta(f"{name}-{h}", ns, age=timedelta(0), labels=labels,
                                 owner=self._ownerref(dep), annotations={}),
                                 "spec": {"replicas": 0, "selector": {"matchLabels": labels}, "template": t}})  # fmt: skip
        if rollout and current is not active:
            rev = str(max(revisions) + 1)
            current["metadata"].setdefault("annotations", {})["deployment.kubernetes.io/revision"] = rev
            dep["metadata"].setdefault("annotations", {})["deployment.kubernetes.io/revision"] = rev
        replicas = dep["spec"].get("replicas", 1)
        broken = None
        if not rollout:
            sample = next(iter(self._pods_for(ns, current["spec"]["selector"]["matchLabels"])), None)
            if sample is not None:
                waiting = [((cs.get("state") or {}).get("waiting") or {}).get("reason")
                           for cs in sample["status"].get("containerStatuses", [])]  # fmt: skip
                broken = ("crash" if "CrashLoopBackOff" in waiting else "imagepull" if "ImagePullBackOff" in waiting
                          else "pending" if sample["status"]["phase"] == "Pending" else None)  # fmt: skip
        if rollout:
            for rs in rs_list:
                for p in self._pods_for(ns, rs["spec"]["selector"]["matchLabels"]):
                    self._store.pop(("Pod", ns, p["metadata"]["name"]), None)
        for rs in rs_list:
            if rs is not current:
                rs["spec"]["replicas"] = 0
                rs["status"] = {"replicas": 0, "observedGeneration": 1}
        cur_pods = self._pods_for(ns, current["spec"]["selector"]["matchLabels"])
        for p in cur_pods[replicas:]:
            self._store.pop(("Pod", ns, p["metadata"]["name"]), None)
        for i in range(len(cur_pods), replicas):
            pod_name = f"{current['metadata']['name']}-{_hash(str(time.time()) + str(i), 5)}"
            self._put(self._make_pod(ns, pod_name, dict(current["spec"]["template"]["metadata"]["labels"]),
                                     current["spec"]["template"]["spec"], self._ownerref(current),
                                     ["node-02", "node-01"][i % 2], broken, timedelta(seconds=5)))  # fmt: skip
        current["spec"]["replicas"] = replicas
        current["status"] = {"replicas": replicas, "readyReplicas": replicas, "availableReplicas": replicas}
        if dep["spec"].get("paused"):
            return
        self._sync_workload_status(dep)

    # ------------------------------------------------------------------ API
    def info(self) -> dict[str, Any]:
        return {"connected": True, "configured": True, "context": "demo-cluster", "server": "https://demo.invalid:6443",
                "version": VERSION, "demo": True}  # fmt: skip

    def list(self, kind, namespace=None, *, label_selector=None, field_selector=None):
        sel = _parse_selector(label_selector)
        fsel = _parse_selector(field_selector)
        with self._lock:
            items = []
            for (k, ns, _), obj in self._store.items():
                if k != kind.kind or (namespace and kind.namespaced and ns != namespace):
                    continue
                labels = obj["metadata"].get("labels") or {}
                if any(labels.get(a) != b for a, b in sel.items()):
                    continue
                if fsel and not _field_match(obj, fsel):
                    continue
                items.append(copy.deepcopy(obj))
        return sorted(items, key=lambda o: (o["metadata"].get("namespace", ""), o["metadata"]["name"]))

    def get(self, kind, name, namespace=None):
        with self._lock:
            obj = self._store.get(self._key(kind.kind, name, namespace))
            if obj is None:
                raise K8sNotFound(f'{kind.key} "{name}" not found', params={"status": 404})
            return copy.deepcopy(obj)

    def _validate(self, manifest: dict[str, Any]) -> None:
        meta = manifest.get("metadata") or {}
        info = BY_KIND[manifest["kind"]]
        if info.namespaced and meta.get("namespace") and ("Namespace", "", meta["namespace"]) not in self._store:
            raise K8sNotFound(f'namespaces "{meta["namespace"]}" not found', params={"status": 404})
        if manifest["kind"] in ("Deployment", "StatefulSet", "DaemonSet"):
            spec = manifest.get("spec") or {}
            tmpl_labels = ((spec.get("template") or {}).get("metadata") or {}).get("labels") or {}
            sel = (spec.get("selector") or {}).get("matchLabels") or {}
            if not sel or any(tmpl_labels.get(k) != v for k, v in sel.items()):
                raise K8sInvalid(
                    f'{manifest["kind"]}.apps "{meta.get("name")}" is invalid: spec.template.metadata.labels: '
                    "Invalid value: selector does not match template labels",
                    params={"status": 422, "causes": [{"field": "spec.template.metadata.labels",
                                                       "message": "`selector` does not match template `labels`"}]},
                )  # fmt: skip
            if not (spec.get("template") or {}).get("spec", {}).get("containers"):
                raise K8sInvalid("spec.template.spec.containers: Required value",
                                 params={"status": 422, "causes": [{"field": "spec.template.spec.containers",
                                                                    "message": "Required value"}]})  # fmt: skip

    def apply(self, manifest, *, dry_run=False, force=False):
        with self._lock:
            self._validate(manifest)
            info = BY_KIND[manifest["kind"]]
            meta = manifest["metadata"]
            key = self._key(info.kind, meta["name"], meta.get("namespace"))
            existing = self._store.get(key)
            obj = _merge(copy.deepcopy(existing), copy.deepcopy(manifest)) if existing else copy.deepcopy(manifest)
            obj["metadata"]["generation"] = (existing or {}).get("metadata", {}).get("generation", 0) + 1
            if dry_run:
                obj["metadata"].setdefault("uid", _uid())
                obj["metadata"].setdefault("creationTimestamp", _ts(timedelta(0)))
                return obj
            self._put(obj)
            self._after_write(obj)
            return copy.deepcopy(obj)

    def create(self, manifest, *, dry_run=False):
        with self._lock:
            info = BY_KIND[manifest["kind"]]
            meta = manifest.setdefault("metadata", {})
            if not meta.get("name") and meta.get("generateName"):
                meta["name"] = meta["generateName"] + _hash(str(time.time()), 5)
            if self._key(info.kind, meta["name"], meta.get("namespace")) in self._store:
                raise K8sConflict(f'{info.key} "{meta["name"]}" already exists', params={"status": 409})
            return self.apply(manifest, dry_run=dry_run)

    def _after_write(self, obj: dict[str, Any]) -> None:
        kind = obj["kind"]
        if kind == "Deployment":
            self._reconcile_deployment(obj)
        elif kind in ("StatefulSet", "DaemonSet"):
            self._sync_workload_status(obj)
        elif kind == "Service":
            self._sync_endpoints(obj["metadata"]["namespace"], obj["metadata"]["name"])
        elif kind == "Namespace":
            obj.setdefault("status", {"phase": "Active"})
        elif kind == "Job":
            obj.setdefault("status", {"active": 1, "startTime": _ts(timedelta(0))})

    def patch(self, kind, name, namespace, body, *, patch_type="merge", dry_run=False):
        with self._lock:
            key = self._key(kind.kind, name, namespace)
            obj = self._store.get(key)
            if obj is None:
                raise K8sNotFound(f'{kind.key} "{name}" not found', params={"status": 404})
            restart = "kubectl.kubernetes.io/restartedAt" in str(body)
            if patch_type == "json":
                new = _json_patch(copy.deepcopy(obj), body)
            else:
                new = _merge(copy.deepcopy(obj), copy.deepcopy(body))
            new["metadata"]["generation"] = obj["metadata"].get("generation", 1) + 1
            if dry_run:
                return new
            self._put(new)
            if kind.kind == "Deployment":
                self._reconcile_deployment(new, restart=restart)
            elif kind.kind == "Node":
                pass
            else:
                self._after_write(new)
            return copy.deepcopy(new)

    def delete(self, kind, name, namespace, *, propagation="Background"):
        with self._lock:
            key = self._key(kind.kind, name, namespace)
            obj = self._store.pop(key, None)
            if obj is None:
                raise K8sNotFound(f'{kind.key} "{name}" not found', params={"status": 404})
            uid = obj["metadata"]["uid"]
            if kind.kind == "Namespace":
                for k in [k for k in self._store if k[1] == name]:
                    self._store.pop(k, None)
            else:
                self._cascade(uid)
            if kind.kind == "Pod":
                self._recreate_owned_pod(obj)
            return {"kind": "Status", "status": "Success"}

    def _cascade(self, uid: str) -> None:
        children = [k for k, o in self._store.items()
                    if any(r.get("uid") == uid for r in o["metadata"].get("ownerReferences", []))]  # fmt: skip
        for k in children:
            child = self._store.pop(k)
            self._cascade(child["metadata"]["uid"])

    def _recreate_owned_pod(self, pod: dict[str, Any]) -> None:
        owners = pod["metadata"].get("ownerReferences") or []
        if not owners or owners[0]["kind"] not in ("ReplicaSet", "StatefulSet", "DaemonSet"):
            return
        ns = pod["metadata"]["namespace"]
        new = copy.deepcopy(pod)
        if owners[0]["kind"] == "ReplicaSet":
            new["metadata"]["name"] = pod["metadata"]["name"].rsplit("-", 1)[0] + "-" + _hash(str(time.time()), 5)
        new["metadata"]["uid"] = _uid()
        new["metadata"]["creationTimestamp"] = _ts(timedelta(0))
        self._put(new)
        for (k, n, _), o in list(self._store.items()):
            if k in ("Deployment", "StatefulSet", "DaemonSet") and n == ns:
                self._sync_workload_status(o)

    def pod_logs(self, name, namespace, *, container=None, tail_lines=None, since_seconds=None,
                 timestamps=False, previous=False, limit_bytes=None):  # fmt: skip
        pod = self.get(KINDS["pods"], name, namespace)
        lines = list(_demo_log_lines(pod, container, previous, count=max(50, min(tail_lines or 200, 2000))))
        if tail_lines is not None:
            lines = lines[-tail_lines:] if tail_lines > 0 else []
        if not timestamps:
            lines = [ln.split(" ", 1)[1] for ln in lines]
        text = "\n".join(lines) + ("\n" if lines else "")
        if limit_bytes:
            text = text[:limit_bytes]
        return text

    def stream_pod_logs(self, name, namespace, *, container=None, tail_lines=None, since_time=None):
        pod = self.get(KINDS["pods"], name, namespace)
        return _DemoLogStream(pod, container, tail_lines or 50)

    def evict(self, name, namespace):
        pod = self.get(KINDS["pods"], name, namespace)
        labels = pod["metadata"].get("labels") or {}
        for (k, ns, _), pdb in self._store.items():
            if k == "PodDisruptionBudget" and ns == namespace:
                sel = pdb["spec"].get("selector", {}).get("matchLabels", {})
                if sel and all(labels.get(a) == b for a, b in sel.items()) and \
                        pdb.get("status", {}).get("disruptionsAllowed", 1) < 1:  # fmt: skip
                    raise K8sConflict("Cannot evict pod as it would violate the pod's disruption budget.",
                                      params={"status": 429, "reason": "TooManyRequests"})  # fmt: skip
        self.delete(KINDS["pods"], name, namespace)

    def node_metrics(self):
        out = []
        for (k, _, name), node in self._store.items():
            if k != "Node":
                continue
            ready = any(c["type"] == "Ready" and c["status"] == "True" for c in node["status"]["conditions"])
            if not ready:
                continue
            seed = int(_hash(name, 4), 16)
            cpu_m = 400 + seed % 1800
            mem_mi = 3000 + seed % 9000
            out.append({"metadata": {"name": name}, "timestamp": _ts(timedelta(seconds=15)), "window": "20s",
                        "usage": {"cpu": f"{cpu_m}m", "memory": f"{mem_mi}Mi"}})  # fmt: skip
        return out

    def pod_metrics(self, namespace=None):
        out = []
        for (k, ns, name), pod in self._store.items():
            if k != "Pod" or (namespace and ns != namespace) or pod["status"]["phase"] != "Running":
                continue
            seed = int(_hash(name, 4), 16)
            containers = []
            for c in pod["spec"]["containers"]:
                limit = ((c.get("resources") or {}).get("limits") or {}).get("memory", "256Mi")
                from .quantity import bytes_

                lim_mi = (bytes_(limit) or 268435456) // 2**20
                mem = int(lim_mi * (0.35 + (seed % 55) / 100))
                containers.append({"name": c["name"], "usage": {"cpu": f"{5 + seed % 240}m", "memory": f"{mem}Mi"}})
            out.append({"metadata": {"name": name, "namespace": ns}, "timestamp": _ts(timedelta(seconds=15)),
                        "window": "20s", "containers": containers})  # fmt: skip
        return out


def _parse_selector(selector: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (selector or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().rstrip("=").rstrip("!")] = v.strip().lstrip("=")
    return out


def _field_match(obj: dict[str, Any], fsel: dict[str, str]) -> bool:
    for path, value in fsel.items():
        cur: Any = obj
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        if str(cur) != value:
            return False
    return True


def _json_patch(obj: dict[str, Any], ops: list[dict[str, Any]]) -> dict[str, Any]:
    """Minimal RFC 6902 (add / replace / remove on object paths) for the demo."""
    for op in ops:
        parts = [p.replace("~1", "/").replace("~0", "~") for p in op["path"].lstrip("/").split("/")]
        parent: Any = obj
        for p in parts[:-1]:
            parent = parent.setdefault(p, {})
        if op["op"] in ("add", "replace"):
            parent[parts[-1]] = copy.deepcopy(op["value"])
        elif op["op"] == "remove":
            parent.pop(parts[-1], None)
        else:
            raise K8sInvalid(f"unsupported JSON patch op {op['op']}")
    return obj


def _merge(base: Any, patch: Any) -> Any:
    """JSON merge patch (RFC 7386), close enough to server-side apply for the demo."""
    if not isinstance(patch, dict):
        return patch
    if not isinstance(base, dict):
        base = {}
    for k, v in patch.items():
        if v is None:
            base.pop(k, None)
        else:
            base[k] = _merge(base.get(k), v)
    return base


_WEB = ['10.244.2.1 - - "GET / HTTP/1.1" 200 615 "-" "kube-probe/1.31"',
        '192.168.10.50 - - "GET /products/42 HTTP/1.1" 200 5123 "-" "Mozilla/5.0"',
        '192.168.10.50 - - "GET /static/app.js HTTP/1.1" 304 0 "-" "Mozilla/5.0"',
        '192.168.10.50 - - "POST /cart HTTP/1.1" 201 87 "-" "Mozilla/5.0"',
        '192.168.10.50 - - "GET /favicon.ico HTTP/1.1" 404 153 "-" "Mozilla/5.0"']  # fmt: skip
_API_CRASH = ["INFO  Starting shop-api 2.4.1 (profile=production)", "INFO  Loading configuration from environment",
              "INFO  Connecting to database postgres.production.svc:5432",
              "WARN  Database connection attempt 1/3 failed: connect ECONNREFUSED 10.96.12.5:5432",
              "WARN  Database connection attempt 2/3 failed: connect ECONNREFUSED 10.96.12.5:5432",
              "WARN  Database connection attempt 3/3 failed: connect ECONNREFUSED 10.96.12.5:5432",
              "ERROR Fatal: unable to connect to database after 3 attempts", "ERROR Exiting with code 1"]  # fmt: skip
_GENERIC = ["INFO  request completed status=200 duration_ms=12", "INFO  healthcheck ok",
            "DEBUG cache hit ratio=0.93", "INFO  request completed status=200 duration_ms=48",
            "WARN  slow request path=/api/orders duration_ms=1240"]  # fmt: skip


def _demo_log_lines(pod: dict[str, Any], container: str | None, previous: bool, count: int) -> Iterator[str]:
    name = pod["metadata"]["name"]
    statuses = pod["status"].get("containerStatuses") or []
    crash = any(((s.get("state") or {}).get("waiting") or {}).get("reason") == "CrashLoopBackOff" for s in statuses)
    if not statuses:
        return
    start = datetime.now(UTC) - timedelta(seconds=count * 3)
    if crash:
        source = _API_CRASH
        count = len(_API_CRASH)
    else:
        source = _WEB if "web" in name or "nginx" in str(pod["spec"]["containers"][0]["image"]) else _GENERIC
    for i in range(count):
        ts = (start + timedelta(seconds=i * 3)).strftime("%Y-%m-%dT%H:%M:%S.%f000Z")
        yield f"{ts} [DEMO] {source[i % len(source)]}"


class _DemoLogStream(LogStream):
    def __init__(self, pod: dict[str, Any], container: str | None, tail: int) -> None:
        self._pod = pod
        self._container = container
        self._tail = tail
        self._closed = threading.Event()

    def __iter__(self) -> Iterator[str]:
        lines = list(_demo_log_lines(self._pod, self._container, False, 200))[-self._tail:]
        yield from lines
        statuses = self._pod["status"].get("containerStatuses") or []
        if not statuses or any((s.get("state") or {}).get("waiting") for s in statuses):
            return
        i = 0
        while not self._closed.wait(1.0):
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f000Z")
            yield f"{ts} [DEMO] {_GENERIC[i % len(_GENERIC)]}"
            i += 1

    def close(self) -> None:
        self._closed.set()
