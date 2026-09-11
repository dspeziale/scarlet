"""Deployment engine against the fake Podman host."""

import pytest

from app.extensions import db
from app.models.enums import DeploymentStatus
from app.repositories import DeploymentRepository, InstanceRepository, VersionRepository
from app.services.deployment_service import DeploymentService
from tests.conftest import build_example_package, upload_package

pytestmark = pytest.mark.integration


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


def test_full_deployment_success(app, fake_ssh, podman_host, customer_api, released_version):
    state = fake_ssh.state_for(podman_host.name)
    deployments = deploy(app, released_version, podman_host)
    dep = deployments[0]
    assert dep.status == DeploymentStatus.SUCCESS.value, dep.error_message
    names = [s.name for s in dep.steps]
    for expected in (
        "validate",
        "preflight",
        "prepare",
        "transfer",
        "verify",
        "extract",
        "configure",
        "hook_pre_deploy",
        "hook_migrate",
        "install",
        "activate",
        "start",
        "health",
        "hook_post_deploy",
        "finalize",
        "cleanup",
    ):
        assert expected in names, names
    assert all(s.status == "SUCCESS" for s in dep.steps), [
        (s.name, s.status, s.error_message) for s in dep.steps
    ]
    # remote side effects
    assert (
        "customer-api" in state.containers and state.containers["customer-api"].status == "running"
    )
    assert state.containers["customer-api"].labels["scarlet.version"] == "1.0.0"
    assert (
        state.symlinks["/opt/scarlet/applications/customer-api/current"]
        == "/opt/scarlet/applications/customer-api/releases/1.0.0"
    )
    assert "/opt/scarlet/applications/customer-api/releases/1.0.0/manifest.yaml" in state.files
    env_file = state.files[
        "/opt/scarlet/applications/customer-api/shared/config/scarlet.env"
    ].decode()
    assert "SCARLET_VERSION=1.0.0" in env_file and "LOG_LEVEL=info" in env_file
    assert len(state.hook_log) == 3
    # staging cleaned
    assert not any(f.endswith(".scarlet.tar.gz") for f in state.files if "/staging/" in f)
    # control-plane state
    instance = InstanceRepository().get_for(customer_api.id, podman_host.id)
    assert instance.current_version_id == released_version.id
    assert instance.desired_version_id == released_version.id
    assert instance.actual_state == "RUNNING" and instance.health_status == "HEALTHY"
    assert not instance.drift_detected
    # audit
    from app.models.audit import AuditLog

    actions = {a.action for a in db.session.execute(db.select(AuditLog)).scalars()}
    assert {
        "DEPLOYMENT_STARTED",
        "DEPLOYMENT_COMPLETED",
        "PACKAGE_UPLOADED",
        "VERSION_RELEASED",
    } <= actions
    assert all(
        not any(w in str(a.details) for w in ("test-only-password",))
        for a in db.session.execute(db.select(AuditLog)).scalars()
    )


def test_upgrade_records_previous_version_and_rollback(
    app, fake_ssh, admin_client, podman_host, customer_api, released_version, example_dir, tmp_path
):
    deploy(app, released_version, podman_host)
    result = build_example_package(example_dir, "podman-app", "1.1.0", tmp_path, secrets=None)
    assert upload_package(admin_client, result.output_path).status_code == 201
    v2 = VersionRepository().by_app_and_version(customer_api.id, "1.1.0")
    dep2 = deploy(app, v2, podman_host)[0]
    assert dep2.status == "SUCCESS", dep2.error_message
    assert dep2.previous_version_id == released_version.id
    instance = InstanceRepository().get_for(customer_api.id, podman_host.id)
    assert (
        instance.current_version.version == "1.1.0" and instance.previous_version.version == "1.0.0"
    )
    state = fake_ssh.state_for(podman_host.name)
    assert state.containers["customer-api"].labels["scarlet.version"] == "1.1.0"
    assert (
        "/opt/scarlet/applications/customer-api/releases/1.0.0/manifest.yaml" in state.files
    )  # old release preserved
    # rollback
    with app.test_request_context():
        rb = DeploymentService().rollback(
            application_id=customer_api.id, host_id=podman_host.id, reason="bug", user=_admin()
        )
    rb = DeploymentRepository().get(rb.id)
    assert rb.kind == "ROLLBACK" and rb.status == "SUCCESS", rb.error_message
    instance = InstanceRepository().get_for(customer_api.id, podman_host.id)
    assert (
        instance.current_version.version == "1.0.0" and instance.previous_version.version == "1.1.0"
    )
    assert state.containers["customer-api"].labels["scarlet.version"] == "1.0.0"
    assert state.symlinks["/opt/scarlet/applications/customer-api/current"].endswith("/1.0.0")


def test_transfer_checksum_failure_marks_transfer_failed(
    app, fake_ssh, podman_host, customer_api, released_version
):
    state = fake_ssh.state_for(podman_host.name)
    state.fail_on["fs.sha256"] = (0, "")  # returns empty stdout -> checksum mismatch
    dep = deploy(app, released_version, podman_host)[0]
    assert dep.status == DeploymentStatus.TRANSFER_FAILED.value
    assert dep.error_code == "FILE_TRANSFER_ERROR"
    assert "customer-api" not in state.containers


def test_health_failure_triggers_auto_rollback(
    app, fake_ssh, admin_client, podman_host, customer_api, released_version, example_dir, tmp_path
):
    deploy(app, released_version, podman_host)
    result = build_example_package(example_dir, "podman-app", "2.0.0", tmp_path, secrets=None)
    assert upload_package(admin_client, result.output_path).status_code == 201
    v2 = VersionRepository().by_app_and_version(customer_api.id, "2.0.0")
    state = fake_ssh.state_for(podman_host.name)
    state.health_http_status = 503
    dep = deploy(app, v2, podman_host, auto_rollback=True)[0]
    assert dep.status == DeploymentStatus.ROLLED_BACK.value, dep.error_message
    assert dep.error_code == "HEALTH_CHECK_FAILED"
    assert any(s.name == "auto_rollback" and s.status == "SUCCESS" for s in dep.steps)
    instance = InstanceRepository().get_for(customer_api.id, podman_host.id)
    assert instance.current_version.version == "1.0.0"
    assert state.containers["customer-api"].labels["scarlet.version"] == "1.0.0"


def test_health_failure_without_auto_rollback_requires_rollback(
    app, fake_ssh, podman_host, customer_api, released_version
):
    state = fake_ssh.state_for(podman_host.name)
    state.health_http_status = 500
    dep = deploy(app, released_version, podman_host, auto_rollback=False)[0]
    assert (
        dep.status == DeploymentStatus.HEALTH_CHECK_FAILED.value
    )  # no previous release -> nothing to roll back to
    instance = InstanceRepository().get_for(customer_api.id, podman_host.id)
    assert instance.current_version_id is None  # never finalized
    assert instance.desired_version_id == released_version.id  # desired recorded
    assert instance.health_status == "UNHEALTHY"


def test_start_failure(app, fake_ssh, podman_host, customer_api, released_version):
    state = fake_ssh.state_for(podman_host.name)
    state.fail_on["runtime.podman.run"] = (125, "Error: image not found")
    dep = deploy(app, released_version, podman_host)[0]
    assert dep.status == DeploymentStatus.START_FAILED.value
    step = next(s for s in dep.steps if s.name == "start")
    assert step.status == "FAILED" and "image not found" in (step.stderr or "")


def test_hook_failure_aborts_before_install(
    app, fake_ssh, podman_host, customer_api, released_version
):
    state = fake_ssh.state_for(podman_host.name)
    state.fail_on["builder.hook"] = (1, "migration failed")
    dep = deploy(app, released_version, podman_host)[0]
    assert dep.status in {DeploymentStatus.INSTALL_FAILED.value, DeploymentStatus.FAILED.value}
    assert "customer-api" not in state.containers
    assert "/opt/scarlet/applications/customer-api/current" not in state.symlinks


def test_conflicting_deployment_rejected(app, podman_host, customer_api, released_version):
    from app.errors import ConflictError
    from app.models.deployment import Deployment

    dep = Deployment(
        reference="DEP-X",
        application_id=customer_api.id,
        version_id=released_version.id,
        target_id=podman_host.id,
        environment_id=podman_host.environment_id,
        status="TRANSFERRING",
    )
    db.session.add(dep)
    db.session.commit()
    with app.test_request_context(), pytest.raises(ConflictError):
        DeploymentService().create(
            application_id=customer_api.id,
            version_id=released_version.id,
            host_ids=[podman_host.id],
            user=_admin(),
        )


def test_incompatible_runtime_rejected(app, customer_api, released_version):
    from app.errors import ValidationError
    from tests.conftest import make_host

    k8s = make_host(name="k8s-01", runtime="KUBERNETES")
    with app.test_request_context(), pytest.raises(ValidationError):
        DeploymentService().create(
            application_id=customer_api.id,
            version_id=released_version.id,
            host_ids=[k8s.id],
            user=_admin(),
        )


def test_unreachable_host_fails_preflight(
    app, fake_ssh, podman_host, customer_api, released_version
):
    fake_ssh.state_for(podman_host.name).unreachable = True
    dep = deploy(app, released_version, podman_host)[0]
    assert dep.status in {
        DeploymentStatus.FAILED.value,
        DeploymentStatus.QUEUED.value,
        DeploymentStatus.PREFLIGHT_FAILED.value,
    }
    assert dep.error_code in {"SSH_CONNECTION_ERROR", None} or "unreachable" in (
        dep.error_message or ""
    )


def test_missing_secret_blocks_deployment(
    app, fake_ssh, admin_client, podman_host, example_dir, tmp_path
):
    from tests.conftest import make_application

    make_application(code="secret-app")
    result = build_example_package(
        example_dir, "podman-app", "1.0.0", tmp_path, application="secret-app"
    )
    assert upload_package(admin_client, result.output_path).status_code == 201
    from app.repositories import ApplicationRepository

    version = VersionRepository().by_app_and_version(
        ApplicationRepository().by_code("secret-app").id, "1.0.0"
    )
    from app.errors import ValidationError

    with app.test_request_context(), pytest.raises(ValidationError) as exc:
        DeploymentService().create(
            application_id=version.application_id,
            version_id=version.id,
            host_ids=[podman_host.id],
            user=_admin(),
        )
    assert "DB_PASSWORD" in str(exc.value.errors)
