"""Host service (test connection / discover) and lifecycle operations against the fake host."""

import pytest

from app.models.enums import OperationType
from app.repositories import InstanceRepository, UserRepository
from app.services.deployment_service import DeploymentService
from app.services.host_service import HostService
from app.services.lifecycle_service import LifecycleService
from app.services.reconciliation_service import ReconciliationService

pytestmark = pytest.mark.integration


def _admin():
    return UserRepository().by_username("admin")


def _deployed(app, version, host):
    with app.test_request_context():
        batch = DeploymentService().create(
            application_id=version.application_id,
            version_id=version.id,
            host_ids=[host.id],
            user=_admin(),
        )
    from app.repositories import DeploymentRepository

    dep = DeploymentRepository().get(batch.deployments[0].id)
    assert dep.status == "SUCCESS", dep.error_message
    return dep


def test_test_connection_and_discover(app, fake_ssh, podman_host):
    with app.test_request_context():
        result = HostService().test_connection(podman_host, user=_admin())
    assert result["ok"] and result["remote_user"] == "scarlet"
    assert podman_host.status == "ONLINE"
    with app.test_request_context():
        data = HostService().discover(podman_host, user=_admin())
    assert data["os"]["name"] == "Oracle Linux Server"
    assert (
        data["runtimes"]["PODMAN"]["available"] and data["runtimes"]["PODMAN"]["rootless"] is True
    )
    assert data["runtimes"]["DOCKER"]["available"] is False
    assert podman_host.os_name == "Oracle Linux Server" and podman_host.cpu_count == 4
    assert podman_host.runtime_version == "4.9.4" and podman_host.runtime_rootless is True
    caps = {c.runtime_type: c for c in podman_host.capabilities}
    assert caps["PODMAN"].available and not caps["KUBERNETES"].available
    # discovery must not modify the host: only read-only commands
    state = fake_ssh.state_for(podman_host.name)
    mutating = [
        c
        for c in state.commands
        if c.split()[0] in {"mkdir", "rm", "mv", "ln", "tar"} or " run " in c
    ]
    assert not mutating, mutating


def test_discover_unreachable_marks_offline(app, fake_ssh, podman_host):
    fake_ssh.state_for(podman_host.name).unreachable = True
    from app.errors import SSHConnectionError

    with app.test_request_context(), pytest.raises(SSHConnectionError):
        HostService().test_connection(podman_host, user=_admin())
    assert podman_host.status == "OFFLINE" and "unreachable" in podman_host.last_error


def test_host_without_credential_fails_clearly(app):
    from tests.conftest import make_host

    host = make_host(name="nocred", with_credential=False)
    from app.errors import SSHAuthenticationError

    with app.test_request_context(), pytest.raises(SSHAuthenticationError):
        HostService().test_connection(host, user=_admin())


def _op(app, op, application, host, **params):
    with app.test_request_context():
        operation = LifecycleService().request(
            op,
            application_id=application.id,
            host_id=host.id,
            user=_admin(),
            parameters=params,
            sync=True,
        )
    from app.repositories import OperationRepository

    return OperationRepository().get(operation.id)


def test_lifecycle_operations_are_idempotent(
    app, fake_ssh, podman_host, customer_api, released_version
):
    _deployed(app, released_version, podman_host)
    state = fake_ssh.state_for(podman_host.name)
    status = _op(app, "STATUS", customer_api, podman_host)
    assert (
        status.status == "SUCCESS"
        and status.result["state"] == "RUNNING"
        and status.result["version"] == "1.0.0"
    )
    start = _op(app, "START", customer_api, podman_host)
    assert start.result_code == "ALREADY_RUNNING"
    stop = _op(app, "STOP", customer_api, podman_host)
    assert stop.result_code == "STOPPED" and state.containers["customer-api"].status == "exited"
    stop2 = _op(app, "STOP", customer_api, podman_host)
    assert stop2.result_code == "ALREADY_STOPPED"
    instance = InstanceRepository().get_for(customer_api.id, podman_host.id)
    assert instance.desired_state == "STOPPED" and instance.actual_state == "STOPPED"
    start = _op(app, "START", customer_api, podman_host)
    assert start.result_code == "STARTED" and state.containers["customer-api"].status == "running"
    restart = _op(app, "RESTART", customer_api, podman_host)
    assert restart.result_code == "RESTARTED"
    health = _op(app, "HEALTH", customer_api, podman_host)
    assert health.result["status"] == "HEALTHY"
    version = _op(app, "VERSION", customer_api, podman_host)
    assert version.result_code == "MATCH"
    logs = _op(app, "LOGS", customer_api, podman_host, lines=50, search="started")
    assert (
        logs.status == "SUCCESS"
        and logs.result["count"] >= 1
        and all("started" in line for line in logs.result["lines"])
    )


def test_logs_parameters_validated(app, podman_host, customer_api, released_version):
    _deployed(app, released_version, podman_host)
    from app.errors import ValidationError

    with app.test_request_context(), pytest.raises(ValidationError):
        LifecycleService().request(
            "LOGS",
            application_id=customer_api.id,
            host_id=podman_host.id,
            user=_admin(),
            parameters={"since": "10m; id"},
        )
    with app.test_request_context(), pytest.raises(ValidationError):
        LifecycleService().request(
            "LOGS",
            application_id=customer_api.id,
            host_id=podman_host.id,
            user=_admin(),
            parameters={"lines": 100000},
        )


def test_operation_on_undeployed_app_rejected(app, podman_host, customer_api):
    from app.errors import NotFoundError

    with app.test_request_context(), pytest.raises(NotFoundError):
        LifecycleService().request(
            "START", application_id=customer_api.id, host_id=podman_host.id, user=_admin()
        )


def test_reconciliation_detects_drift(app, fake_ssh, podman_host, customer_api, released_version):
    _deployed(app, released_version, podman_host)
    state = fake_ssh.state_for(podman_host.name)
    # someone stops the container behind SCARLET's back
    state.containers["customer-api"].status = "exited"
    with app.test_request_context():
        summary = ReconciliationService().reconcile_host(podman_host)
    assert summary["drift"] == 1
    instance = InstanceRepository().get_for(customer_api.id, podman_host.id)
    assert (
        instance.drift_detected
        and instance.drift_type == "UNEXPECTED_STOP"
        and instance.actual_state == "STOPPED"
    )
    # version drift: label changed
    state.containers["customer-api"].status = "running"
    state.containers["customer-api"].labels["scarlet.version"] = "0.9.0"
    with app.test_request_context():
        ReconciliationService().reconcile_host(podman_host)
    instance = InstanceRepository().get_for(customer_api.id, podman_host.id)
    assert instance.drift_type == "VERSION" and instance.actual_version == "0.9.0"


def test_reconciliation_remediates_when_enabled(
    app, fake_ssh, podman_host, customer_api, released_version
):
    _deployed(app, released_version, podman_host)
    state = fake_ssh.state_for(podman_host.name)
    state.containers["customer-api"].status = "exited"
    from app.services.settings_service import get_settings_service

    get_settings_service().set("SCARLET_RECONCILE_AUTO_REMEDIATE", True)
    with app.test_request_context():
        summary = ReconciliationService().reconcile_host(podman_host)
    assert summary["remediated"] == 1
    assert state.containers["customer-api"].status == "running"
    instance = InstanceRepository().get_for(customer_api.id, podman_host.id)
    assert not instance.drift_detected


def test_host_operations_via_tasks(app, podman_host):
    from app.services.operation_service import OperationService
    from app.tasks.host_tasks import discover_host, test_ssh_connection

    ops = OperationService()
    with app.test_request_context():
        op = ops.create(OperationType.TEST_CONNECTION, target=podman_host, user=_admin())
    test_ssh_connection.apply(args=[op.id])
    from app.repositories import OperationRepository

    op = OperationRepository().get(op.id)
    assert op.status == "SUCCESS" and op.result_code == "ONLINE"
    with app.test_request_context():
        op2 = ops.create(OperationType.DISCOVER, target=podman_host, user=_admin())
    discover_host.apply(args=[op2.id])
    op2 = OperationRepository().get(op2.id)
    assert op2.status == "SUCCESS" and op2.result["runtimes"]["PODMAN"]["available"]
