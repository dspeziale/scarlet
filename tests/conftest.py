"""Shared pytest fixtures.

The suite runs entirely in-process: SQLite in memory, Celery in eager mode,
and a fake SSH layer that simulates an Oracle Linux host with Podman.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("SCARLET_ENV", "testing")
os.environ.setdefault("SCARLET_LOG_FORMAT", "text")
os.environ.setdefault("SCARLET_LOG_LEVEL", "WARNING")
os.environ["SCARLET_INITIAL_ADMIN_PASSWORD"] = "Adm1n-Passw0rd-Str0ng!"

ADMIN_PASSWORD = "Adm1n-Passw0rd-Str0ng!"
OPERATOR_PASSWORD = "0perator-Passw0rd!"
VIEWER_PASSWORD = "V1ewer-Passw0rd!!"
PROD_OPERATOR_PASSWORD = "Pr0d-0perator-Passw0rd!"


@pytest.fixture(scope="session")
def example_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture()
def app(tmp_path):
    from app import create_app
    from app.extensions import db
    from app.ssh.fake import FakeSSHClientFactory

    app = create_app(
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SCARLET_ARTIFACT_PATH": str(tmp_path / "artifacts"),
            "SCARLET_UPLOAD_TMP_PATH": str(tmp_path / "uploads"),
            "SCARLET_LOG_PATH": str(tmp_path / "logs"),
            "WTF_CSRF_ENABLED": False,
            "CELERY_TASK_ALWAYS_EAGER": True,
            "SCARLET_HEALTH_CHECK_INTERVAL": 0,
            "RATELIMIT_ENABLED": False,
        }
    )
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/api/_boom")  # test-only endpoint used by the traceback leakage test
    def _boom():
        raise RuntimeError("internal detail that must not leak")

    fake = FakeSSHClientFactory()
    app.extensions["scarlet_ssh_factory"] = fake
    with app.app_context():
        db.create_all()
        from app.seed import seed_all

        seed_all(with_demo=False)
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def fake_ssh(app):
    return app.extensions["scarlet_ssh_factory"]


@pytest.fixture()
def db_session(app):
    from app.extensions import db

    return db.session


@pytest.fixture()
def users(app):
    """Create operator / viewer / prod operator users in addition to the seeded admin."""
    from app.repositories import UserRepository
    from app.services.user_service import UserService

    svc = UserService()
    repo = UserRepository()
    created = {"admin": repo.by_username("admin")}
    created["operator"] = svc.create_user(
        username="operator",
        password=OPERATOR_PASSWORD,
        roles=["OPERATOR"],
        must_change_password=False,
    )
    created["viewer"] = svc.create_user(
        username="viewer", password=VIEWER_PASSWORD, roles=["VIEWER"], must_change_password=False
    )
    created["prod_operator"] = svc.create_user(
        username="prodop",
        password=PROD_OPERATOR_PASSWORD,
        roles=["PROD_OPERATOR"],
        must_change_password=False,
    )
    return created


def _login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.get_json()
    return client


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_client(app, users):
    return _login(app.test_client(), "admin", ADMIN_PASSWORD)


@pytest.fixture()
def operator_client(app, users):
    return _login(app.test_client(), "operator", OPERATOR_PASSWORD)


@pytest.fixture()
def viewer_client(app, users):
    return _login(app.test_client(), "viewer", VIEWER_PASSWORD)


@pytest.fixture()
def prod_operator_client(app, users):
    return _login(app.test_client(), "prodop", PROD_OPERATOR_PASSWORD)


@pytest.fixture()
def environments(app):
    from app.repositories import EnvironmentRepository

    repo = EnvironmentRepository()
    return {"DEV": repo.by_code("DEV"), "PROD": repo.by_code("PROD")}


def make_host(
    name="dev-app-01", env="DEV", runtime="PODMAN", with_credential=True, approved_key=True
):
    """Create a host with an encrypted dummy credential (never a real secret) and an approved key."""
    from app.extensions import db
    from app.models.enums import HostKeyStatus
    from app.repositories import EnvironmentRepository
    from app.services.host_service import HostService

    environment = EnvironmentRepository().by_code(env)
    host = HostService().create(
        {
            "name": name,
            "hostname": f"{name}.example.internal",
            "ip_address": None,
            "ssh_port": 22,
            "ssh_username": "scarlet",
            "environment_id": environment.id,
            "runtime_type": runtime,
            "description": "test host",
        }
    )
    if with_credential:
        HostService().set_credential(
            host, credential_type="PASSWORD", secret="test-only-password-not-real"
        )
    if approved_key:
        host.ssh_host_key_type = "ssh-ed25519"
        host.ssh_host_key = "AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyForTests000000000000000000000000000"
        host.ssh_fingerprint = "SHA256:testfingerprint"
        host.ssh_host_key_status = HostKeyStatus.APPROVED.value
        db.session.commit()
    return host


def make_application(code="customer-api", runtime="PODMAN", allow_hooks=True, **extra):
    from app.services.application_service import ApplicationService

    data = {
        "name": code.replace("-", " ").title(),
        "code": code,
        "runtime_type": runtime,
        "default_port": 8080,
        "healthcheck_type": "HTTP",
        "healthcheck_url": "/",
        "healthcheck_port": 8080,
        "allow_hooks": allow_hooks,
        "allowed_runtimes": ["PODMAN", "DOCKER"],
    }
    data.update(extra)
    return ApplicationService().create(data)


def build_example_package(example_dir: Path, name: str, version: str, out_dir: Path, **overrides):
    """Build a package from an example directory, optionally patching the manifest."""
    import shutil

    import yaml

    from app.deployment.packager import build_package

    src = out_dir / f"src-{name}-{version}"
    if src.exists():
        shutil.rmtree(src)
    shutil.copytree(example_dir / name, src)
    if overrides:
        manifest_path = src / "manifest.yaml"
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        for key, value in overrides.items():
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
        manifest_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return build_package(src, out_dir, version=version)


def upload_package(client, path: Path, **form):
    with open(path, "rb") as fh:
        data = {"file": (fh, path.name)}
        data.update({k: str(v) for k, v in form.items()})
        return client.post("/api/packages/upload", data=data, content_type="multipart/form-data")


@pytest.fixture()
def podman_host(app):
    return make_host()


@pytest.fixture()
def prod_host(app):
    return make_host(name="prod-app-01", env="PROD")


@pytest.fixture()
def customer_api(app):
    return make_application()


@pytest.fixture()
def released_version(app, admin_client, customer_api, example_dir, tmp_path):
    """Upload the podman example (without secrets requirement) and return the ApplicationVersion."""
    from app.repositories import VersionRepository

    result = build_example_package(example_dir, "podman-app", "1.0.0", tmp_path, secrets=None)
    response = upload_package(admin_client, result.output_path)
    assert response.status_code == 201, response.get_json()
    return VersionRepository().by_app_and_version(customer_api.id, "1.0.0")
