"""Kubernetes targets, end to end, against the in-memory cluster.

These exercise the mode that has no shell at all: the target is registered with a kubeconfig,
SCARLET never opens an SSH session, and everything (configuration, objects, rollout, drift,
rollback, removal) happens through the cluster API.
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import ApplicationState, DeploymentStatus, OperationType
from app.repositories import DeploymentRepository, InstanceRepository
from app.services.deployment_service import DeploymentService
from app.services.host_service import HostService
from app.services.lifecycle_service import LifecycleService
from app.services.preflight_service import PreflightService

pytestmark = pytest.mark.integration

SECRET = "inventory-web-scarlet-env"
NAMESPACE = "inventory"


def _admin():
    from app.repositories import UserRepository

    return UserRepository().by_username("admin")


def deploy(app, version, host, **kw):
    with app.test_request_context():
        batch = DeploymentService().create(
            application_id=version.application_id,
            version_id=version.id,
            host_ids=[host.id],
            user=_admin(),
            **kw,
        )
    return [DeploymentRepository().get(d.id) for d in batch.deployments]


# --- registration ------------------------------------------------------------------------


def test_cluster_target_needs_no_ssh(cluster_host):
    assert cluster_host.is_cluster_managed
    assert cluster_host.access_mode == "API"
    assert cluster_host.active_credential is None, "a cluster target has no SSH credential"
    assert cluster_host.kubernetes_credential is not None


def test_test_connection_talks_to_the_cluster(app, cluster, cluster_host):
    with app.test_request_context():
        result = HostService().test_connection(cluster_host, user=_admin())
    assert result["ok"] and result["access_mode"] == "API"
    assert result["cluster_version"] == cluster.version
    assert cluster_host.status == "ONLINE"


def test_discover_reports_cluster_facts(app, cluster, cluster_host):
    with app.test_request_context():
        data = HostService().discover(cluster_host, user=_admin())
    assert data["kubernetes"]["version"] == cluster.version
    assert data["kubernetes"]["namespace"] == NAMESPACE
    assert data["runtimes"]["KUBERNETES"]["available"] is True
    assert cluster_host.kubernetes_version == cluster.version


def test_unreachable_cluster_marks_the_target_offline(app, cluster, cluster_host):
    from app.errors import ScarletError

    cluster.reachable = False
    with app.test_request_context(), pytest.raises(ScarletError):
        HostService().test_connection(cluster_host, user=_admin())
    assert cluster_host.status == "OFFLINE"


def test_cluster_executor_refuses_shell_commands(cluster_host):
    from app.errors import RuntimeOperationError
    from app.runtimes.access import open_executor
    from app.ssh.command import SystemCommands

    executor = open_executor(cluster_host)
    with pytest.raises(RuntimeOperationError) as excinfo:
        executor.run(SystemCommands.whoami())
    assert "no SSH shell" in excinfo.value.message


# --- preflight ---------------------------------------------------------------------------


def test_preflight_checks_the_cluster_not_the_machine(app, cluster, cluster_host, k8s_version):
    with app.test_request_context():
        result = PreflightService().run(
            k8s_version.application, k8s_version, cluster_host, remote=True
        )
    names = {check.name: check for check in result.checks}
    assert names["cluster"].status == "PASS"
    assert names["access"].status == "PASS"
    assert names["permissions"].status == "PASS"
    assert names["objects"].status == "PASS"
    for machine_check in ("ssh", "disk", "memory", "base_path", "ports"):
        assert machine_check not in names, f"{machine_check} does not apply to a cluster"
    assert result.ok


def test_preflight_fails_when_the_credential_cannot_create(app, cluster, cluster_host, k8s_version):
    cluster.denied.add("create:deployments")
    with app.test_request_context():
        result = PreflightService().run(
            k8s_version.application, k8s_version, cluster_host, remote=True
        )
    permissions = next(c for c in result.checks if c.name == "permissions")
    assert permissions.status == "FAIL"
    assert not result.ok


# --- deployment --------------------------------------------------------------------------


def test_deployment_applies_objects_without_touching_a_filesystem(
    app, cluster, cluster_host, inventory_web, k8s_version
):
    dep = deploy(app, k8s_version, cluster_host)[0]
    assert dep.status == DeploymentStatus.SUCCESS.value, dep.error_message

    names = [step.name for step in dep.steps]
    for expected in (
        "validate",
        "preflight",
        "configure",
        "install",
        "start",
        "health",
        "finalize",
    ):
        assert expected in names, names
    for absent in ("prepare", "transfer", "verify", "extract", "activate", "cleanup"):
        assert absent not in names, f"{absent} has no meaning on a cluster target"

    assert "Deployment/inventory-web" in cluster.applied
    assert "Service/inventory-web" in cluster.applied
    deployment = cluster.deployment("inventory-web", NAMESPACE)
    assert deployment is not None
    assert deployment["metadata"]["labels"]["scarlet.io/version"] == "1.0.0"
    assert deployment["metadata"]["labels"]["scarlet.io/application"] == "inventory-web"
    assert deployment["spec"]["replicas"] == 2


def test_configuration_becomes_a_secret_wired_with_env_from(
    app, cluster, cluster_host, inventory_web, k8s_version
):
    deploy(app, k8s_version, cluster_host)
    secret = cluster.secret(SECRET, NAMESPACE)
    assert secret is not None, "the rendered configuration must exist in the cluster"
    assert secret["stringData"]["SCARLET_APPLICATION"] == "inventory-web"
    assert secret["stringData"]["SCARLET_VERSION"] == "1.0.0"

    container = cluster.deployment("inventory-web", NAMESPACE)["spec"]["template"]["spec"][
        "containers"
    ][0]
    refs = [(e.get("secretRef") or {}).get("name") for e in container["envFrom"]]
    assert SECRET in refs


def test_instance_records_the_actual_state(app, cluster, cluster_host, inventory_web, k8s_version):
    deploy(app, k8s_version, cluster_host)
    instance = InstanceRepository().get_for(inventory_web.id, cluster_host.id)
    assert instance.actual_version == "1.0.0"
    assert instance.actual_state == ApplicationState.RUNNING.value
    assert instance.actual_replicas == 2
    assert instance.drift_detected is False


def test_failed_rollout_reports_cluster_events(
    app, cluster, cluster_host, inventory_web, k8s_version
):
    cluster.break_image("docker.io/library/nginx:1.27-alpine")
    cluster.add_event(
        NAMESPACE,
        object_name="inventory-web",
        reason="FailedCreate",
        message="pods are not becoming ready",
    )
    dep = deploy(app, k8s_version, cluster_host)[0]
    assert dep.status != DeploymentStatus.SUCCESS.value
    assert "rollout" in (dep.error_message or "").lower()


# --- lifecycle ---------------------------------------------------------------------------


def _run(app, operation_type, application, host, **parameters):
    with app.test_request_context():
        return LifecycleService().request(
            operation_type,
            application_id=application.id,
            host_id=host.id,
            user=_admin(),
            parameters=parameters or None,
            sync=True,
        )


def test_stop_and_start_scale_the_deployment(
    app, cluster, cluster_host, inventory_web, k8s_version
):
    deploy(app, k8s_version, cluster_host)
    _run(app, OperationType.STOP, inventory_web, cluster_host)
    assert cluster.deployment("inventory-web", NAMESPACE)["spec"]["replicas"] == 0

    _run(app, OperationType.START, inventory_web, cluster_host)
    assert cluster.deployment("inventory-web", NAMESPACE)["spec"]["replicas"] == 2


def test_restart_annotates_the_pod_template(app, cluster, cluster_host, inventory_web, k8s_version):
    deploy(app, k8s_version, cluster_host)
    _run(app, OperationType.RESTART, inventory_web, cluster_host)
    annotations = cluster.deployment("inventory-web", NAMESPACE)["spec"]["template"]["metadata"][
        "annotations"
    ]
    assert "kubectl.kubernetes.io/restartedAt" in annotations


def test_logs_come_from_the_pods(app, cluster, cluster_host, inventory_web, k8s_version):
    deploy(app, k8s_version, cluster_host)
    cluster.logs["inventory-web-0"] = "hello from pod zero"
    operation = _run(app, OperationType.LOGS, inventory_web, cluster_host, lines=50)
    payload = operation.result or {}
    assert any("hello from pod zero" in line for line in payload.get("lines", []))


# --- drift and reconciliation ------------------------------------------------------------


def test_drift_is_detected_when_someone_scales_the_deployment_away(
    app, cluster, cluster_host, inventory_web, k8s_version
):
    deploy(app, k8s_version, cluster_host)
    # somebody scales it to zero directly in the cluster
    cluster.deployment("inventory-web", NAMESPACE)["spec"]["replicas"] = 0
    cluster.deployment("inventory-web", NAMESPACE)["status"]["readyReplicas"] = 0

    from app.services.reconciliation_service import ReconciliationService

    with app.test_request_context():
        result = ReconciliationService().reconcile_host(cluster_host)
    assert result["drift"] == 1
    instance = InstanceRepository().get_for(inventory_web.id, cluster_host.id)
    assert instance.drift_detected is True
    assert instance.drift_type in {"STATE", "UNEXPECTED_STOP"}


# --- rollback and removal ----------------------------------------------------------------


def test_rollback_returns_to_the_previous_version(
    app, cluster, cluster_host, inventory_web, k8s_version, admin_client, example_dir, tmp_path
):
    from tests.conftest import build_example_package, upload_package

    deploy(app, k8s_version, cluster_host)
    built = build_example_package(example_dir, "kubernetes-app", "1.1.0", tmp_path)
    assert upload_package(admin_client, built.output_path).status_code == 201
    from app.repositories import VersionRepository

    v2 = VersionRepository().by_app_and_version(inventory_web.id, "1.1.0")
    deploy(app, v2, cluster_host)
    assert (
        cluster.deployment("inventory-web", NAMESPACE)["metadata"]["labels"]["scarlet.io/version"]
        == "1.1.0"
    )

    with app.test_request_context():
        requested = DeploymentService().rollback(
            application_id=inventory_web.id, host_id=cluster_host.id, user=_admin()
        )
    rolled = DeploymentRepository().get(requested.id)
    assert rolled.status == DeploymentStatus.SUCCESS.value, rolled.error_message
    assert (
        cluster.deployment("inventory-web", NAMESPACE)["metadata"]["labels"]["scarlet.io/version"]
        == "1.0.0"
    )


def test_remove_deletes_every_object_of_the_application(
    app, cluster, cluster_host, inventory_web, k8s_version
):
    deploy(app, k8s_version, cluster_host)
    assert cluster.kinds(NAMESPACE)

    from app.deployment.remote_layout import RemoteLayout
    from app.runtimes.access import build_host_info, open_executor
    from app.runtimes.base import RuntimeContext
    from app.runtimes.factory import RuntimeFactory

    with app.test_request_context():
        info = build_host_info(cluster_host)
        ctx = RuntimeContext(
            executor=open_executor(cluster_host),
            host=info,
            application_code=inventory_web.code,
            layout=RemoteLayout(info.base_path, inventory_web.code),
        )
        RuntimeFactory.get("KUBERNETES").remove(ctx)

    remaining = [
        f"{kind}/{name}"
        for (kind, name), doc in cluster.docs(NAMESPACE).items()
        if (doc.get("metadata", {}).get("labels") or {}).get("scarlet.io/application")
        == "inventory-web"
    ]
    assert remaining == [], remaining


def test_cleanup_skips_cluster_targets(app, cluster, cluster_host, inventory_web, k8s_version):
    from app.services.cleanup_service import CleanupService

    deploy(app, k8s_version, cluster_host)
    with app.test_request_context():
        result = CleanupService().cleanup_remote_releases(cluster_host, inventory_web)
    assert result["skipped"] == "cluster target"
    db.session.rollback()
