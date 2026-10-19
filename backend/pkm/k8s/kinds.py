"""Registry of the Kubernetes resource kinds managed by PKM.

Only the kinds listed here can be read or written through the API: this keeps
the attack surface explicit and lets the UI know what each kind supports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import K8sUnsupported, NotFound


@dataclass(frozen=True)
class KindInfo:
    key: str  # URL key, plural lowercase (e.g. "deployments")
    kind: str
    api_version: str
    namespaced: bool
    category: str
    guide: str | None = None
    min_version: str | None = None  # minimum Kubernetes version for this apiVersion
    actions: frozenset[str] = field(default_factory=frozenset)
    workload: bool = False  # can be created by operators (deploy permission)
    has_logs: bool = False

    @property
    def group(self) -> str:
        return self.api_version.split("/")[0] if "/" in self.api_version else ""

    @property
    def version(self) -> str:
        return self.api_version.split("/")[-1]

    def collection_path(self, namespace: str | None) -> str:
        base = f"/apis/{self.api_version}" if self.group else f"/api/{self.version}"
        if self.namespaced and namespace:
            return f"{base}/namespaces/{namespace}/{self.key}"
        return f"{base}/{self.key}"

    def item_path(self, name: str, namespace: str | None) -> str:
        return f"{self.collection_path(namespace)}/{name}"

    def public(self) -> dict[str, object]:
        return {
            "key": self.key,
            "kind": self.kind,
            "apiVersion": self.api_version,
            "namespaced": self.namespaced,
            "category": self.category,
            "guide": self.guide,
            "actions": sorted(self.actions),
            "hasLogs": self.has_logs,
            "workload": self.workload,
        }


_K = KindInfo
KINDS: dict[str, KindInfo] = {
    k.key: k
    for k in [
        _K("nodes", "Node", "v1", False, "cluster", "node", actions=frozenset({"cordon", "uncordon", "drain"})),
        _K("namespaces", "Namespace", "v1", False, "cluster", "namespace", actions=frozenset({"delete"})),
        _K("events", "Event", "v1", True, "cluster", "troubleshooting"),
        _K("pods", "Pod", "v1", True, "workloads", "pod", actions=frozenset({"delete", "restart"}),
           workload=True, has_logs=True),
        _K("deployments", "Deployment", "apps/v1", True, "workloads", "deployment",
           actions=frozenset({"scale", "restart", "pause", "resume", "rollback", "delete", "edit"}), workload=True),
        _K("replicasets", "ReplicaSet", "apps/v1", True, "workloads", "replicaset",
           actions=frozenset({"delete"}), workload=True),
        _K("statefulsets", "StatefulSet", "apps/v1", True, "workloads", "statefulset",
           actions=frozenset({"scale", "restart", "delete", "edit"}), workload=True),
        _K("daemonsets", "DaemonSet", "apps/v1", True, "workloads", "daemonset",
           actions=frozenset({"restart", "delete", "edit"}), workload=True),
        _K("jobs", "Job", "batch/v1", True, "workloads", "job", actions=frozenset({"delete"}), workload=True),
        _K("cronjobs", "CronJob", "batch/v1", True, "workloads", "cronjob", min_version="1.21",
           actions=frozenset({"suspend", "resume", "trigger", "delete", "edit"}), workload=True),
        _K("services", "Service", "v1", True, "networking", "service",
           actions=frozenset({"delete", "edit"}), workload=True),
        _K("ingresses", "Ingress", "networking.k8s.io/v1", True, "networking", "ingress", min_version="1.19",
           actions=frozenset({"delete", "edit"}), workload=True),
        _K("endpoints", "Endpoints", "v1", True, "networking", "networking"),
        _K("persistentvolumes", "PersistentVolume", "v1", False, "storage", "persistent-volume",
           actions=frozenset({"delete"})),
        _K("persistentvolumeclaims", "PersistentVolumeClaim", "v1", True, "storage", "persistent-volume-claim",
           actions=frozenset({"delete"}), workload=True),
        _K("storageclasses", "StorageClass", "storage.k8s.io/v1", False, "storage", "storage-class"),
        _K("configmaps", "ConfigMap", "v1", True, "config", "configmap",
           actions=frozenset({"delete", "edit"}), workload=True),
        _K("secrets", "Secret", "v1", True, "config", "secret", actions=frozenset({"delete"})),
        _K("poddisruptionbudgets", "PodDisruptionBudget", "policy/v1", True, "reliability", "alta-disponibilita",
           min_version="1.21", actions=frozenset({"delete", "edit"}), workload=True),
        _K("horizontalpodautoscalers", "HorizontalPodAutoscaler", "autoscaling/v2", True, "reliability",
           "replica", min_version="1.23", actions=frozenset({"delete", "edit"}), workload=True),
    ]
}  # fmt: skip

BY_KIND: dict[str, KindInfo] = {k.kind: k for k in KINDS.values()}

# Deleting these is considered high-risk (data loss or wide impact).
HIGH_RISK_DELETE = {"namespaces", "persistentvolumes", "persistentvolumeclaims", "secrets", "nodes"}


def get_kind(key: str) -> KindInfo:
    info = KINDS.get(key)
    if info is None:
        raise NotFound(f"unknown resource type '{key}'", params={"kind": key})
    return info


def kind_for_manifest(api_version: str, kind: str) -> KindInfo:
    info = BY_KIND.get(kind)
    if info is None:
        raise K8sUnsupported(
            f"resource kind '{kind}' is not managed by this application",
            params={"kind": kind, "supported": sorted(BY_KIND)},
        )
    if info.api_version != api_version:
        raise K8sUnsupported(
            f"apiVersion '{api_version}' for {kind} is not supported; use '{info.api_version}'",
            params={"kind": kind, "apiVersion": api_version, "expected": info.api_version},
        )
    return info
