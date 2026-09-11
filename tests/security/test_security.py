"""Security regression tests: injection, traversal, authorization, PROD protection, leakage."""

import io
import tarfile

import pytest

from tests.conftest import build_example_package, make_application, make_host, upload_package

pytestmark = pytest.mark.security


# --- authentication / authorization ------------------------------------------------------------


def test_anonymous_api_is_rejected(client):
    assert client.get("/api/hosts").status_code == 401
    assert client.post("/api/hosts", json={}).status_code == 401
    r = client.get("/hosts")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_viewer_cannot_mutate(viewer_client, podman_host, customer_api):
    assert viewer_client.get("/api/hosts").status_code == 200
    assert viewer_client.post("/api/hosts", json={"name": "x"}).status_code == 403
    assert (
        viewer_client.post(
            f"/api/applications/{customer_api.id}/start", json={"host_id": podman_host.id}
        ).status_code
        == 403
    )
    assert viewer_client.get("/api/audit").status_code == 403
    assert viewer_client.get("/api/users").status_code == 403


def test_operator_cannot_touch_prod(operator_client, prod_host, customer_api, released_version):
    r = operator_client.post(
        "/api/deployments",
        json={
            "application_id": customer_api.id,
            "version_id": released_version.id,
            "host_ids": [prod_host.id],
            "reason": "x",
            "confirmation": "DEPLOY TO PROD",
        },
    )
    assert r.status_code == 403
    assert "PRODUCTION" in r.get_json()["error"]["message"]
    # but DEV is fine
    dev = make_host(name="dev-2")
    r = operator_client.post(
        "/api/deployments/preflight",
        json={
            "application_id": customer_api.id,
            "version_id": released_version.id,
            "host_ids": [dev.id],
            "remote": False,
        },
    )
    assert r.status_code == 200


def test_prod_deployment_requires_typed_confirmation_and_reason(
    prod_operator_client, prod_host, customer_api, released_version
):
    base = {
        "application_id": customer_api.id,
        "version_id": released_version.id,
        "host_ids": [prod_host.id],
    }
    r = prod_operator_client.post(
        "/api/deployments", json={**base, "confirmation": "DEPLOY TO PROD"}
    )
    assert r.status_code == 400 and "reason" in str(r.get_json()["error"]).lower()
    r = prod_operator_client.post(
        "/api/deployments", json={**base, "reason": "CHG-1", "confirmation": "deploy to prod"}
    )
    assert r.status_code == 403 and r.get_json()["error"]["code"] == "PRODUCTION_SAFETY"
    r = prod_operator_client.post(
        "/api/deployments", json={**base, "reason": "CHG-1", "confirmation": "DEPLOY TO PROD"}
    )
    assert r.status_code == 202, r.get_json()


def test_prod_stop_requires_stop_phrase(
    app, prod_operator_client, prod_host, customer_api, released_version
):
    prod_operator_client.post(
        "/api/deployments",
        json={
            "application_id": customer_api.id,
            "version_id": released_version.id,
            "host_ids": [prod_host.id],
            "reason": "CHG-1",
            "confirmation": "DEPLOY TO PROD",
        },
    )
    r = prod_operator_client.post(
        f"/api/applications/{customer_api.id}/stop",
        json={"host_id": prod_host.id, "reason": "x", "confirmation": "DEPLOY TO PROD"},
    )
    assert r.status_code == 403
    r = prod_operator_client.post(
        f"/api/applications/{customer_api.id}/stop",
        json={"host_id": prod_host.id, "reason": "x", "confirmation": "STOP PROD"},
    )
    assert r.status_code in (200, 202)


def test_login_lockout_and_rate_limit_config(app, client, users):
    for _ in range(app.config["SCARLET_MAX_FAILED_LOGINS"]):
        assert (
            client.post(
                "/api/auth/login", json={"username": "operator", "password": "wrong"}
            ).status_code
            == 401
        )
    r = client.post(
        "/api/auth/login", json={"username": "operator", "password": "0perator-Passw0rd!"}
    )
    assert r.status_code == 401 and "locked" in r.get_json()["error"]["message"].lower()


def test_unknown_user_message_identical(client, users):
    a = client.post("/api/auth/login", json={"username": "nobody", "password": "x"}).get_json()[
        "error"
    ]["message"]
    b = client.post("/api/auth/login", json={"username": "operator", "password": "x"}).get_json()[
        "error"
    ]["message"]
    assert a == b


def test_session_invalidated_after_password_change(app, users):
    c = app.test_client()
    c.post("/api/auth/login", json={"username": "operator", "password": "0perator-Passw0rd!"})
    assert c.get("/api/auth/me").status_code == 200
    r = c.post(
        "/api/auth/password",
        json={"current_password": "0perator-Passw0rd!", "new_password": "N3w-Str0ng-Passw0rd!"},
    )
    assert r.status_code == 200
    assert c.get("/api/auth/me").status_code == 401  # generation bumped


# --- credential leakage --------------------------------------------------------------------------------


def test_credentials_never_returned(admin_client, podman_host):
    r = admin_client.get(f"/api/hosts/{podman_host.id}")
    body = r.get_data(as_text=True)
    assert "test-only-password" not in body
    assert "encrypted_secret" not in body
    r = admin_client.post(
        f"/api/hosts/{podman_host.id}/credentials",
        json={"credential_type": "PASSWORD", "secret": "another-secret-value"},
    )
    assert r.status_code == 201 and "another-secret-value" not in r.get_data(as_text=True)
    audit = admin_client.get("/api/audit?action=CREDENTIAL").get_data(as_text=True)
    assert "another-secret-value" not in audit and "test-only-password" not in audit


def test_configuration_secrets_masked(admin_client, customer_api):
    r = admin_client.put(
        f"/api/applications/{customer_api.id}/configuration/DEV",
        json={
            "entries": [
                {"key": "DB_PASSWORD", "value": "super-secret-db", "value_type": "SECRET"},
                {"key": "LOG_LEVEL", "value": "debug", "value_type": "CONFIG"},
            ]
        },
    )
    assert r.status_code == 200
    body = admin_client.get(f"/api/applications/{customer_api.id}/configuration/DEV").get_data(
        as_text=True
    )
    assert "super-secret-db" not in body and "debug" in body
    audit = admin_client.get("/api/audit?action=CONFIGURATION").get_data(as_text=True)
    assert "super-secret-db" not in audit


def test_log_redaction():
    from app.config.logging import redact

    text = "password=abc123 token: xyz Authorization: Bearer scl_secret -----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"
    out = redact(text)
    assert (
        "abc123" not in out and "xyz" not in out and "scl_secret" not in out and "abc\n" not in out
    )


def test_error_responses_hide_tracebacks(app, admin_client):
    r = admin_client.get("/api/_boom")
    assert r.status_code == 500
    body = r.get_data(as_text=True)
    assert "internal detail" not in body and "Traceback" not in body
    assert r.get_json()["error"]["request_id"]


# --- injection / traversal --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "h; rm -rf /"},
        {"hostname": "$(id).example"},
        {"ssh_username": "root; id"},
        {"ssh_port": 99999},
        {"ip_address": "127.0.0.1"},
        {"remote_base_path": "/opt/scarlet/../etc"},
    ],
)
def test_host_input_validation(admin_client, payload):
    data = {
        "name": "valid-host",
        "hostname": "valid.example.internal",
        "ssh_username": "scarlet",
        "ssh_port": 22,
        "environment": "DEV",
        "runtime_type": "PODMAN",
    }
    data.update(payload)
    r = admin_client.post("/api/hosts", json=data)
    assert r.status_code == 400, r.get_json()


def test_application_code_injection_rejected(admin_client):
    r = admin_client.post(
        "/api/applications", json={"name": "x", "code": "app; rm -rf /", "runtime_type": "PODMAN"}
    )
    assert r.status_code == 400
    r = admin_client.post(
        "/api/applications",
        json={
            "name": "x",
            "code": "ok-app",
            "runtime_type": "PODMAN",
            "healthcheck_command": "true; rm -rf /",
        },
    )
    assert r.status_code == 400


def test_package_traversal_rejected_on_upload(admin_client, customer_api, tmp_path):
    path = tmp_path / "evil.scarlet.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        manifest = b"manifest_version: 1\napplication: customer-api\nversion: 9.9.9\nruntime: podman\nimage:\n  name: x/y\n  tag: '1'\n"
        info = tarfile.TarInfo("manifest.yaml")
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
        evil = tarfile.TarInfo("../../etc/cron.d/pwn")
        evil.size = 4
        tar.addfile(evil, io.BytesIO(b"pwn\n"))
    r = upload_package(admin_client, path)
    assert r.status_code == 201
    data = r.get_json()["data"]
    assert data["status"] == "INVALID" and any(
        "Unsafe path" in e for e in data["validation_errors"]
    )
    assert data["version_id"] is None


def test_manifest_for_unregistered_application_rejected(admin_client, example_dir, tmp_path):
    result = build_example_package(
        example_dir, "podman-app", "1.0.0", tmp_path, application="ghost-app", secrets=None
    )
    r = upload_package(admin_client, result.output_path)
    assert r.get_json()["data"]["status"] == "INVALID"


def test_release_immutability(admin_client, customer_api, released_version, example_dir, tmp_path):
    result = build_example_package(
        example_dir, "podman-app", "1.0.0", tmp_path, secrets=None, description="changed content"
    )
    r = upload_package(admin_client, result.output_path)
    data = r.get_json()["data"]
    assert data["status"] == "INVALID"
    assert any("immutable" in e or "already" in e for e in data["validation_errors"])


def test_hooks_require_application_opt_in(admin_client, example_dir, tmp_path):
    make_application(code="nohooks", allow_hooks=False)
    result = build_example_package(
        example_dir, "podman-app", "1.0.0", tmp_path, application="nohooks", secrets=None
    )
    data = upload_package(admin_client, result.output_path).get_json()["data"]
    assert data["status"] == "INVALID" and any("hooks" in e for e in data["validation_errors"])


def test_log_viewer_rejects_filesystem_style_input(admin_client, podman_host, customer_api):
    from app.extensions import db
    from app.repositories import InstanceRepository

    inst = InstanceRepository().get_or_create(customer_api.id, podman_host.id)
    inst.current_version_id = customer_api.versions[0].id if customer_api.versions else None
    db.session.commit()
    r = admin_client.post(
        f"/api/applications/{customer_api.id}/logs",
        json={"host_id": podman_host.id, "parameters": {"since": "../../etc/passwd"}},
    )
    assert r.status_code in (400, 404)


def test_no_generic_command_endpoint(app):
    rules = [r.rule for r in app.url_map.iter_rules()]
    assert not any("exec" in r or "shell" in r or "command" in r for r in rules)
    assert app.config["SCARLET_ALLOW_DIAGNOSTIC_SHELL"] is False


def test_open_redirect_blocked(client, users):
    r = client.post(
        "/login?next=https://evil.example/x",
        data={"username": "operator", "password": "0perator-Passw0rd!"},
    )
    assert (
        r.status_code == 302
        and r.headers["Location"].startswith("/")
        and "evil" not in r.headers["Location"]
    )


def test_security_headers(admin_client):
    r = admin_client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert "unsafe-inline" not in r.headers["Content-Security-Policy"].split("style-src")[0]


def test_production_config_validation(monkeypatch):
    from app.config.settings import build_config
    from app.errors import ConfigurationError

    monkeypatch.setenv("SCARLET_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///x.db")
    monkeypatch.setenv("SCARLET_SECRET_KEY", "short")
    with pytest.raises(ConfigurationError) as exc:
        build_config()
    problems = exc.value.details["problems"]
    assert any("SCARLET_SECRET_KEY" in p for p in problems)
    assert any("SQLite" in p for p in problems)
    assert any("ENCRYPTION_KEY" in p for p in problems)
