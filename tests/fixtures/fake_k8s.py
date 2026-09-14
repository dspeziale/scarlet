"""An in-memory Kubernetes cluster for the test suite.

Mirrors what ``FakeSSHClientFactory`` does for hosts: the whole cluster path (preflight,
deploy, scale, rollback, drift, removal) runs against this without a real cluster, and the
objects SCARLET applied can be inspected afterwards.

It implements :class:`app.runtimes.k8s_api.KubernetesApi` faithfully enough to be useful:
a Deployment reports ready replicas only after it is scaled, and an image the fixture marks
as broken never becomes ready, so failure paths can be exercised too.
"""

from __future__ import annotations

import copy
from typing import Any

from app.errors import RuntimeOperationError
from app.runtimes.k8s_api import CLUSTER_KINDS


class FakeCluster:
    """State of one fake cluster, shared by every client built from it."""

    def __init__(self, *, version: str = "v1.29.4") -> None:
        self.version = version
        self.namespaces: set[str] = {"default"}
        #: objects[namespace][(kind, name)] = document
        self.objects: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.logs: dict[str, str] = {}
        self.reachable = True
        self.denied: set[str] = set()  # entries like "create:deployments"
        self.unknown_reviews = False
        self.broken_images: set[str] = set()
        self.applied: list[str] = []  # audit trail of every apply, in order

    # --- helpers for the tests ------------------------------------------------------
    def docs(self, namespace: str = "default") -> dict[tuple[str, str], dict[str, Any]]:
        return self.objects.setdefault(namespace, {})

    def deployment(self, name: str, namespace: str = "default") -> dict[str, Any] | None:
        return self.docs(namespace).get(("Deployment", name))

    def secret(self, name: str, namespace: str = "default") -> dict[str, Any] | None:
        return self.docs(namespace).get(("Secret", name))

    def kinds(self, namespace: str = "default") -> list[str]:
        return sorted({kind for kind, _ in self.docs(namespace)})

    def break_image(self, image: str) -> None:
        """Pods of this image never become ready: the rollout fails like in real life."""
        self.broken_images.add(image)

    def add_event(self, namespace: str, *, object_name: str, reason: str, message: str) -> None:
        self.events.setdefault(namespace, []).append(
            {
                "type": "Warning",
                "reason": reason,
                "message": message,
                "object": f"Deployment/{object_name}",
                "count": 1,
                "last_seen": "2026-01-01T00:00:00Z",
            }
        )


class FakeKubernetesApi:
    """Client bound to a :class:`FakeCluster`."""

    def __init__(self, cluster: FakeCluster) -> None:
        self.cluster = cluster

    def _check_reachable(self) -> None:
        if not self.cluster.reachable:
            raise RuntimeOperationError("Kubernetes API error: cluster unreachable")

    # --- cluster --------------------------------------------------------------------
    def server_version(self) -> dict[str, Any]:
        self._check_reachable()
        return {
            "git_version": self.cluster.version,
            "major": "1",
            "minor": "29",
            "platform": "linux/amd64",
        }

    def namespace_exists(self, name: str) -> bool:
        self._check_reachable()
        return name in self.cluster.namespaces

    def ensure_namespace(self, name: str) -> bool:
        self._check_reachable()
        if name in self.cluster.namespaces:
            return False
        self.cluster.namespaces.add(name)
        return True

    # --- objects --------------------------------------------------------------------
    def apply(self, doc: dict[str, Any], namespace: str) -> str:
        self._check_reachable()
        kind = doc["kind"]
        name = (doc.get("metadata") or {}).get("name")
        if not name:
            raise RuntimeOperationError(f"{kind} without metadata.name")
        target_ns = namespace
        if kind in CLUSTER_KINDS:
            self.cluster.namespaces.add(name)
            self.cluster.applied.append(f"{kind}/{name}")
            return f"{kind}/{name}"
        self.cluster.namespaces.add(target_ns)
        stored = copy.deepcopy(doc)
        stored.setdefault("metadata", {})["namespace"] = target_ns
        if kind == "Deployment":
            previous = self.cluster.docs(target_ns).get((kind, name))
            replicas = int(stored.get("spec", {}).get("replicas") or 0)
            if previous is not None:
                # an apply keeps the replica count already in the cluster unless it changed
                replicas = int(stored.get("spec", {}).get("replicas", replicas) or 0)
            stored.setdefault("spec", {})["replicas"] = replicas
            stored["status"] = self._status_for(stored, replicas)
        self.cluster.docs(target_ns)[(kind, name)] = stored
        self.cluster.applied.append(f"{kind}/{name}")
        return f"{kind}/{name}"

    def _status_for(self, doc: dict[str, Any], replicas: int) -> dict[str, Any]:
        containers = (((doc.get("spec") or {}).get("template") or {}).get("spec") or {}).get(
            "containers"
        ) or []
        image = containers[0].get("image") if containers else None
        broken = image in self.cluster.broken_images
        if replicas == 0:
            ready = 0
            conditions = [{"type": "Available", "status": "False", "reason": "ScaledDown"}]
        elif broken:
            ready = 0
            conditions = [
                {"type": "Progressing", "status": "False", "reason": "ProgressDeadlineExceeded"}
            ]
        else:
            ready = replicas
            conditions = [
                {"type": "Available", "status": "True", "reason": "MinimumReplicasAvailable"}
            ]
        return {
            "readyReplicas": ready,
            "availableReplicas": ready,
            "updatedReplicas": ready,
            "observedGeneration": 1,
            "conditions": conditions,
        }

    def read(self, kind: str, name: str, namespace: str) -> dict[str, Any] | None:
        self._check_reachable()
        return copy.deepcopy(self.cluster.docs(namespace).get((kind, name)))

    def delete(self, kind: str, name: str, namespace: str) -> bool:
        self._check_reachable()
        return self.cluster.docs(namespace).pop((kind, name), None) is not None

    def delete_by_label(self, kinds: tuple[str, ...], namespace: str, selector: str) -> list[str]:
        self._check_reachable()
        key, _, value = selector.partition("=")
        removed: list[str] = []
        for (kind, name), doc in list(self.cluster.docs(namespace).items()):
            if kind not in kinds:
                continue
            labels = (doc.get("metadata") or {}).get("labels") or {}
            if labels.get(key) == value:
                del self.cluster.docs(namespace)[(kind, name)]
                removed.append(f"{kind}/{name}")
        return removed

    # --- workloads ------------------------------------------------------------------
    def scale(self, name: str, namespace: str, replicas: int) -> None:
        self._check_reachable()
        doc = self.cluster.docs(namespace).get(("Deployment", name))
        if doc is None:
            raise RuntimeOperationError(f"Kubernetes API error: Deployment {name} not found")
        doc.setdefault("spec", {})["replicas"] = replicas
        doc["status"] = self._status_for(doc, replicas)

    def restart(self, name: str, namespace: str) -> None:
        self._check_reachable()
        doc = self.cluster.docs(namespace).get(("Deployment", name))
        if doc is None:
            raise RuntimeOperationError(f"Kubernetes API error: Deployment {name} not found")
        annotations = (
            doc.setdefault("spec", {})
            .setdefault("template", {})
            .setdefault("metadata", {})
            .setdefault("annotations", {})
        )
        annotations["kubectl.kubernetes.io/restartedAt"] = "2026-01-01T00:00:00Z"

    def list_pods(self, namespace: str, selector: str) -> list[dict[str, Any]]:
        self._check_reachable()
        key, _, value = selector.partition("=")
        pods: list[dict[str, Any]] = []
        for (kind, name), doc in self.cluster.docs(namespace).items():
            if kind != "Deployment":
                continue
            labels = (doc.get("metadata") or {}).get("labels") or {}
            if labels.get(key) != value:
                continue
            ready = int((doc.get("status") or {}).get("readyReplicas") or 0)
            for index in range(int((doc.get("spec") or {}).get("replicas") or 0)):
                pods.append(
                    {
                        "name": f"{name}-{index}",
                        "phase": "Running" if index < ready else "Pending",
                        "ready": index < ready,
                        "restarts": 0,
                        "node": "node-1",
                        "reason": None,
                        "containers": [],
                    }
                )
        return pods

    def pod_logs(
        self, namespace: str, pod: str, *, lines: int = 200, since_seconds: int | None = None
    ) -> str:
        self._check_reachable()
        return self.cluster.logs.get(pod, f"log line from {pod}")

    def events(
        self, namespace: str, *, selector: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        events = self.cluster.events.get(namespace, [])
        if selector:
            events = [e for e in events if selector in e.get("object", "")]
        return events[:limit]

    def can_i(self, verb: str, resource: str, namespace: str) -> bool | None:
        if self.cluster.unknown_reviews:
            return None
        return f"{verb}:{resource}" not in self.cluster.denied


def install_fake_cluster(app, cluster: FakeCluster | None = None) -> FakeCluster:
    """Register the fake as the cluster client factory for an application."""
    cluster = cluster or FakeCluster()
    app.extensions["scarlet_k8s_api_factory"] = lambda kubeconfig, context=None: FakeKubernetesApi(
        cluster
    )
    app.extensions["scarlet_k8s_cluster"] = cluster
    return cluster
