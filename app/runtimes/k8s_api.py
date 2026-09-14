"""The Kubernetes cluster as a port.

The adapter never imports the official client directly: it asks for a :class:`KubernetesApi`
and works against this small surface. Two reasons.

* The cluster path can be exercised end to end in the test suite with an in-memory fake,
  the same way the SSH path is exercised with ``FakeSSHClientFactory``.
* Everything that touches the cluster goes through one module, so the object kinds SCARLET
  is willing to apply, and the errors it turns them into, are decided in a single place.
"""

from __future__ import annotations

from typing import Any, Protocol

from flask import current_app

from app.config.logging import get_logger
from app.errors import RuntimeOperationError

log = get_logger(__name__)

#: Kinds SCARLET applies inside the target namespace.
NAMESPACED_KINDS: frozenset[str] = frozenset(
    {
        "ConfigMap",
        "CronJob",
        "DaemonSet",
        "Deployment",
        "HorizontalPodAutoscaler",
        "Ingress",
        "Job",
        "NetworkPolicy",
        "PersistentVolumeClaim",
        "PodDisruptionBudget",
        "Role",
        "RoleBinding",
        "Secret",
        "Service",
        "ServiceAccount",
        "StatefulSet",
    }
)

#: Cluster-scoped kinds SCARLET is willing to create.
CLUSTER_KINDS: frozenset[str] = frozenset({"Namespace"})

SUPPORTED_KINDS: frozenset[str] = NAMESPACED_KINDS | CLUSTER_KINDS

#: Deleted, in this order, when an application is removed from a namespace.
CLEANUP_KINDS: tuple[str, ...] = (
    "HorizontalPodAutoscaler",
    "CronJob",
    "Job",
    "Deployment",
    "StatefulSet",
    "DaemonSet",
    "Ingress",
    "Service",
    "NetworkPolicy",
    "PodDisruptionBudget",
    "ConfigMap",
    "Secret",
    "PersistentVolumeClaim",
    "RoleBinding",
    "Role",
    "ServiceAccount",
)


class KubernetesApi(Protocol):
    """What SCARLET needs from a cluster. Implemented for real and for tests."""

    def server_version(self) -> dict[str, Any]: ...

    def ensure_namespace(self, name: str) -> bool:
        """Create the namespace when missing. Returns True when it was created."""

    def namespace_exists(self, name: str) -> bool: ...

    def apply(self, doc: dict[str, Any], namespace: str) -> str:
        """Create or update one object. Returns ``Kind/name``."""

    def read(self, kind: str, name: str, namespace: str) -> dict[str, Any] | None: ...

    def delete(self, kind: str, name: str, namespace: str) -> bool: ...

    def delete_by_label(
        self, kinds: tuple[str, ...], namespace: str, selector: str
    ) -> list[str]: ...

    def scale(self, name: str, namespace: str, replicas: int) -> None: ...

    def restart(self, name: str, namespace: str) -> None: ...

    def list_pods(self, namespace: str, selector: str) -> list[dict[str, Any]]: ...

    def pod_logs(
        self, namespace: str, pod: str, *, lines: int = 200, since_seconds: int | None = None
    ) -> str: ...

    def events(
        self, namespace: str, *, selector: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]: ...

    def can_i(self, verb: str, resource: str, namespace: str) -> bool | None:
        """Ask the cluster whether the credential may do something. None when unknown."""


class OfficialKubernetesApi:
    """Implementation on top of the official ``kubernetes`` client.

    Uses the dynamic client so every supported kind works without maintaining a map of
    api versions and plurals.
    """

    def __init__(self, kubeconfig: str, context: str | None = None) -> None:
        import yaml
        from kubernetes import client as k8s_client
        from kubernetes import config as k8s_config
        from kubernetes import dynamic

        loaded = yaml.safe_load(kubeconfig or "") or {}
        if not loaded:
            raise RuntimeOperationError("The stored kubeconfig is empty or not valid YAML.")
        configuration = k8s_client.Configuration()
        try:
            k8s_config.load_kube_config_from_dict(
                loaded, context=context or None, client_configuration=configuration
            )
        except Exception as exc:  # noqa: BLE001 - the client raises several unrelated types
            raise RuntimeOperationError(f"Unusable kubeconfig: {exc}") from exc
        self._api_client = k8s_client.ApiClient(configuration)
        self._core = k8s_client.CoreV1Api(self._api_client)
        self._apps = k8s_client.AppsV1Api(self._api_client)
        self._version = k8s_client.VersionApi(self._api_client)
        self._auth = k8s_client.AuthorizationV1Api(self._api_client)
        self._dynamic = dynamic.DynamicClient(self._api_client)

    # --- helpers ---------------------------------------------------------------------
    @staticmethod
    def _wrap(exc: Exception, what: str) -> RuntimeOperationError:
        status = getattr(exc, "status", None)
        reason = getattr(exc, "reason", None) or str(exc)
        detail = f"{status} {reason}".strip()
        return RuntimeOperationError(
            f"Kubernetes API error while {what}: {detail}",
            details={"status": status, "reason": str(reason)[:300]},
        )

    def _resource(self, doc_or_kind: dict[str, Any] | str):
        if isinstance(doc_or_kind, dict):
            api_version = doc_or_kind.get("apiVersion")
            kind = doc_or_kind.get("kind")
        else:
            kind, api_version = doc_or_kind, None
        try:
            if api_version:
                return self._dynamic.resources.get(api_version=api_version, kind=kind)
            return self._dynamic.resources.get(kind=kind)
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc, f"resolving kind {kind}") from exc

    # --- cluster ---------------------------------------------------------------------
    def server_version(self) -> dict[str, Any]:
        try:
            info = self._version.get_code()
        except Exception as exc:  # noqa: BLE001
            raise self._wrap(exc, "reading the server version") from exc
        return {
            "git_version": getattr(info, "git_version", None),
            "major": getattr(info, "major", None),
            "minor": getattr(info, "minor", None),
            "platform": getattr(info, "platform", None),
        }

    def namespace_exists(self, name: str) -> bool:
        from kubernetes.client.exceptions import ApiException

        try:
            self._core.read_namespace(name)
            return True
        except ApiException as exc:
            if exc.status in (403, 404):
                return False
            raise self._wrap(exc, f"reading namespace {name}") from exc

    def ensure_namespace(self, name: str) -> bool:
        from kubernetes.client.exceptions import ApiException

        if self.namespace_exists(name):
            return False
        try:
            self._core.create_namespace({"metadata": {"name": name}})
            return True
        except ApiException as exc:
            if exc.status == 409:
                return False
            raise self._wrap(exc, f"creating namespace {name}") from exc

    # --- objects ---------------------------------------------------------------------
    def apply(self, doc: dict[str, Any], namespace: str) -> str:
        from kubernetes.client.exceptions import ApiException

        kind = doc.get("kind", "")
        name = (doc.get("metadata") or {}).get("name", "")
        resource = self._resource(doc)
        target_ns = None if kind in CLUSTER_KINDS else namespace
        try:
            resource.get(name=name, namespace=target_ns)
            resource.patch(
                body=doc,
                name=name,
                namespace=target_ns,
                content_type="application/merge-patch+json",
            )
        except ApiException as exc:
            if exc.status != 404:
                raise self._wrap(exc, f"applying {kind}/{name}") from exc
            try:
                resource.create(body=doc, namespace=target_ns)
            except ApiException as create_exc:
                raise self._wrap(create_exc, f"creating {kind}/{name}") from create_exc
        except Exception as exc:  # noqa: BLE001 - dynamic client wraps 404 in its own type
            if type(exc).__name__ != "NotFoundError":
                raise self._wrap(exc, f"applying {kind}/{name}") from exc
            try:
                resource.create(body=doc, namespace=target_ns)
            except Exception as create_exc:  # noqa: BLE001
                raise self._wrap(create_exc, f"creating {kind}/{name}") from create_exc
        return f"{kind}/{name}"

    def read(self, kind: str, name: str, namespace: str) -> dict[str, Any] | None:
        resource = self._resource(kind)
        try:
            obj = resource.get(name=name, namespace=None if kind in CLUSTER_KINDS else namespace)
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status", None)
            if status == 404 or type(exc).__name__ == "NotFoundError":
                return None
            raise self._wrap(exc, f"reading {kind}/{name}") from exc
        return obj.to_dict() if hasattr(obj, "to_dict") else dict(obj)

    def delete(self, kind: str, name: str, namespace: str) -> bool:
        resource = self._resource(kind)
        try:
            resource.delete(name=name, namespace=None if kind in CLUSTER_KINDS else namespace)
            return True
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status", None)
            if status == 404 or type(exc).__name__ == "NotFoundError":
                return False
            raise self._wrap(exc, f"deleting {kind}/{name}") from exc

    def delete_by_label(self, kinds: tuple[str, ...], namespace: str, selector: str) -> list[str]:
        removed: list[str] = []
        for kind in kinds:
            try:
                resource = self._resource(kind)
            except RuntimeOperationError as exc:
                # The cluster does not serve this kind (an old cluster without Ingress, say).
                log.debug("kind %s not available on the cluster: %s", kind, exc)
                continue
            try:
                listing = resource.get(namespace=namespace, label_selector=selector)
            except Exception as exc:  # noqa: BLE001 - one unreadable kind must not stop the rest
                log.debug("cannot list %s in %s: %s", kind, namespace, exc)
                continue
            for item in getattr(listing, "items", []) or []:
                name = item.metadata.name
                try:
                    resource.delete(name=name, namespace=namespace)
                    removed.append(f"{kind}/{name}")
                except Exception as exc:  # noqa: BLE001
                    log.warning("could not delete %s/%s in %s: %s", kind, name, namespace, exc)
        return removed

    # --- workloads -------------------------------------------------------------------
    def scale(self, name: str, namespace: str, replicas: int) -> None:
        from kubernetes.client.exceptions import ApiException

        try:
            self._apps.patch_namespaced_deployment_scale(
                name, namespace, {"spec": {"replicas": replicas}}
            )
        except ApiException as exc:
            raise self._wrap(exc, f"scaling {name} to {replicas}") from exc

    def restart(self, name: str, namespace: str) -> None:
        from datetime import UTC, datetime

        from kubernetes.client.exceptions import ApiException

        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": datetime.now(UTC).isoformat()
                        }
                    }
                }
            }
        }
        try:
            self._apps.patch_namespaced_deployment(name, namespace, patch)
        except ApiException as exc:
            raise self._wrap(exc, f"restarting {name}") from exc

    def list_pods(self, namespace: str, selector: str) -> list[dict[str, Any]]:
        from kubernetes.client.exceptions import ApiException

        try:
            pods = self._core.list_namespaced_pod(namespace, label_selector=selector)
        except ApiException as exc:
            raise self._wrap(exc, "listing pods") from exc
        out: list[dict[str, Any]] = []
        for pod in pods.items:
            statuses = pod.status.container_statuses or []
            out.append(
                {
                    "name": pod.metadata.name,
                    "phase": pod.status.phase,
                    "ready": all(cs.ready for cs in statuses) if statuses else False,
                    "restarts": sum(cs.restart_count or 0 for cs in statuses),
                    "node": pod.spec.node_name,
                    "reason": pod.status.reason,
                    "containers": [
                        {
                            "name": cs.name,
                            "ready": cs.ready,
                            "restarts": cs.restart_count,
                            "state": next(
                                (
                                    key
                                    for key, value in (
                                        cs.state.to_dict() if cs.state else {}
                                    ).items()
                                    if value
                                ),
                                None,
                            ),
                        }
                        for cs in statuses
                    ],
                }
            )
        return out

    def pod_logs(
        self, namespace: str, pod: str, *, lines: int = 200, since_seconds: int | None = None
    ) -> str:
        from kubernetes.client.exceptions import ApiException

        kwargs: dict[str, Any] = {"tail_lines": lines, "timestamps": True}
        if since_seconds:
            kwargs["since_seconds"] = since_seconds
        try:
            return self._core.read_namespaced_pod_log(pod, namespace, **kwargs)
        except ApiException as exc:
            raise self._wrap(exc, f"reading logs of pod {pod}") from exc

    def events(
        self, namespace: str, *, selector: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        from kubernetes.client.exceptions import ApiException

        try:
            listing = self._core.list_namespaced_event(namespace, limit=200)
        except ApiException:
            return []
        events = []
        for item in listing.items:
            involved = item.involved_object
            if selector and selector not in (involved.name or ""):
                continue
            events.append(
                {
                    "type": item.type,
                    "reason": item.reason,
                    "message": (item.message or "")[:400],
                    "object": f"{involved.kind}/{involved.name}",
                    "count": item.count,
                    "last_seen": str(item.last_timestamp) if item.last_timestamp else None,
                }
            )
        events.sort(key=lambda e: e.get("last_seen") or "", reverse=True)
        return events[:limit]

    def can_i(self, verb: str, resource: str, namespace: str) -> bool | None:
        from kubernetes.client.exceptions import ApiException

        body = {
            "spec": {
                "resourceAttributes": {"namespace": namespace, "verb": verb, "resource": resource}
            }
        }
        try:
            review = self._auth.create_self_subject_access_review(body)
        except ApiException:
            return None
        return bool(getattr(review.status, "allowed", False))


def get_kubernetes_api(kubeconfig: str, context: str | None = None) -> KubernetesApi:
    """Build the cluster client, honouring a factory registered by the tests."""
    factory = None
    try:
        factory = current_app.extensions.get("scarlet_k8s_api_factory")
    except RuntimeError:  # outside an application context (never in production paths)
        factory = None
    if factory is not None:
        return factory(kubeconfig, context)
    return OfficialKubernetesApi(kubeconfig, context)
