"""Unit checks on the Kubernetes adapter's rendering rules.

What SCARLET writes into the objects before applying them is a contract: the released image,
the configuration Secret and the ownership labels. These run without a cluster.
"""

from __future__ import annotations

import pytest

from app.deployment.domain import DesiredApplicationState
from app.deployment.remote_layout import RemoteLayout
from app.errors import RuntimeOperationError
from app.models.enums import DesiredState
from app.runtimes.base import HostInfo, RuntimeContext
from app.runtimes.k8s_api import CLEANUP_KINDS, NAMESPACED_KINDS, SUPPORTED_KINDS
from app.runtimes.kubernetes import APP_LABEL, MANAGED_BY, VERSION_LABEL, KubernetesRuntimeAdapter
from app.ssh.cluster import ClusterExecutor

pytestmark = pytest.mark.unit


def make_ctx(namespace: str = "inventory") -> RuntimeContext:
    return RuntimeContext(
        executor=ClusterExecutor("k8s-01"),
        host=HostInfo(
            name="k8s-01",
            runtime_type="KUBERNETES",
            base_path="/opt/scarlet",
            kubernetes_namespace=namespace,
            kubeconfig="apiVersion: v1",
        ),
        application_code="inventory-web",
        layout=RemoteLayout("/opt/scarlet", "inventory-web"),
    )


def make_desired(**extra) -> DesiredApplicationState:
    manifest = {"kubernetes": {"deployment_name": "inventory-web", "container_name": "web"}}
    manifest.update(extra.pop("manifest", {}))
    return DesiredApplicationState(
        application_code="inventory-web",
        version="2.0.0",
        state=DesiredState.RUNNING,
        replicas=3,
        image="registry.internal/inventory-web:2.0.0",
        manifest=manifest,
        namespace="inventory",
        **extra,
    )


def deployment_doc() -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "inventory-web"},
        "spec": {
            "replicas": 1,
            "template": {"spec": {"containers": [{"name": "web", "image": "nginx:stale"}]}},
        },
    }


def test_the_released_image_wins_over_the_one_in_the_package():
    adapter = KubernetesRuntimeAdapter()
    doc = adapter._decorate(make_ctx(), deployment_doc(), make_desired())
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "registry.internal/inventory-web:2.0.0"


def test_the_configuration_secret_is_wired_with_env_from():
    adapter = KubernetesRuntimeAdapter()
    doc = adapter._decorate(make_ctx(), deployment_doc(), make_desired())
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert container["envFrom"] == [
        {"secretRef": {"name": "inventory-web-scarlet-env", "optional": True}}
    ]


def test_wiring_is_idempotent():
    adapter = KubernetesRuntimeAdapter()
    ctx, desired = make_ctx(), make_desired()
    doc = adapter._decorate(ctx, adapter._decorate(ctx, deployment_doc(), desired), desired)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    assert len(container["envFrom"]) == 1, "applying twice must not duplicate the reference"


def test_ownership_labels_land_on_the_object_and_the_pod_template():
    adapter = KubernetesRuntimeAdapter()
    doc = adapter._decorate(make_ctx(), deployment_doc(), make_desired())
    assert doc["metadata"]["labels"][APP_LABEL] == "inventory-web"
    assert doc["metadata"]["labels"][VERSION_LABEL] == "2.0.0"
    assert doc["metadata"]["labels"][MANAGED_BY] == "scarlet"
    template_labels = doc["spec"]["template"]["metadata"]["labels"]
    assert template_labels[APP_LABEL] == "inventory-web"
    assert template_labels[VERSION_LABEL] == "2.0.0"


def test_desired_replicas_override_the_package():
    adapter = KubernetesRuntimeAdapter()
    doc = adapter._decorate(make_ctx(), deployment_doc(), make_desired())
    assert doc["spec"]["replicas"] == 3


def test_a_workload_without_containers_is_refused():
    adapter = KubernetesRuntimeAdapter()
    doc = {"kind": "Deployment", "metadata": {"name": "x"}, "spec": {"template": {"spec": {}}}}
    with pytest.raises(RuntimeOperationError, match="no container"):
        adapter._decorate(make_ctx(), doc, make_desired())


def test_a_service_only_gets_labels():
    adapter = KubernetesRuntimeAdapter()
    doc = adapter._decorate(
        make_ctx(), {"kind": "Service", "metadata": {"name": "inventory-web"}}, make_desired()
    )
    assert doc["metadata"]["labels"][APP_LABEL] == "inventory-web"
    assert VERSION_LABEL not in doc["metadata"]["labels"]
    assert "spec" not in doc


def test_privileged_cluster_kinds_stay_out_of_release_packages():
    for kind in ("ClusterRole", "ClusterRoleBinding", "CustomResourceDefinition", "Node"):
        assert kind not in SUPPORTED_KINDS


def test_every_namespaced_kind_is_cleaned_up_on_removal():
    assert set(CLEANUP_KINDS) == set(NAMESPACED_KINDS)


def test_the_secret_name_is_derived_from_the_application():
    assert KubernetesRuntimeAdapter().secret_name(make_ctx()) == "inventory-web-scarlet-env"
