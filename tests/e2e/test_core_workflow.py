"""End-to-end: login -> host -> application -> upload -> deploy -> start/status/logs -> rollback, all via HTTP."""

import pytest

from tests.conftest import ADMIN_PASSWORD, build_example_package, upload_package

pytestmark = pytest.mark.e2e


def _ok(response, status=200):
    body = response.get_json()
    statuses = status if isinstance(status, tuple) else (status,)
    assert response.status_code in statuses, body
    assert body["ok"] is True
    return body["data"]


def _wait_operation(client, data):
    op_id = data["id"]
    for _ in range(50):
        op = _ok(client.get(f"/api/operations/{op_id}"))
        if op["is_terminal"]:
            return op
    raise AssertionError("operation did not finish")


def _wait_deployment(client, dep_id):
    for _ in range(50):
        dep = _ok(client.get(f"/api/deployments/{dep_id}"))
        if dep["is_terminal"]:
            return dep
    raise AssertionError("deployment did not finish")


def test_core_workflow(app, fake_ssh, users, example_dir, tmp_path):
    client = app.test_client()
    # 1. login
    me = _ok(client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}))
    assert "deployment.execute" in me["permissions"]
    assert client.get("/").status_code == 200

    # 2. create DEV host + credential + approve host key (via scan path simulated by pending fields)
    host = _ok(
        client.post(
            "/api/hosts",
            json={
                "name": "dev-app-01",
                "hostname": "dev-app-01.example.internal",
                "ssh_username": "scarlet",
                "ssh_port": 22,
                "environment": "DEV",
                "runtime_type": "PODMAN",
            },
        ),
        201,
    )
    _ok(
        client.post(
            f"/api/hosts/{host['id']}/credentials",
            json={"credential_type": "PASSWORD", "secret": "test-only-password"},
        ),
        201,
    )
    from app.extensions import db
    from app.models.host import TargetHost

    h = db.session.get(TargetHost, host["id"])
    (
        h.ssh_pending_fingerprint,
        h.ssh_pending_host_key,
        h.ssh_pending_host_key_type,
        h.ssh_host_key_status,
    ) = ("SHA256:abc", "AAAA", "ssh-ed25519", "PENDING_APPROVAL")
    db.session.commit()
    r = client.post(
        f"/api/hosts/{host['id']}/host-key/approve", json={"fingerprint": "SHA256:wrong"}
    )
    assert r.status_code == 400
    approved = _ok(
        client.post(f"/api/hosts/{host['id']}/host-key/approve", json={"fingerprint": "SHA256:abc"})
    )
    assert approved["ssh_host_key_status"] == "APPROVED"

    # 3. test connection + discover (async operations, eager celery)
    op = _wait_operation(
        client, _ok(client.post(f"/api/hosts/{host['id']}/test-connection"), (200, 202))
    )
    assert op["status"] == "SUCCESS" and op["result_code"] == "ONLINE"
    op = _wait_operation(client, _ok(client.post(f"/api/hosts/{host['id']}/discover"), (200, 202)))
    assert op["status"] == "SUCCESS" and op["result"]["runtimes"]["PODMAN"]["available"]
    detail = _ok(client.get(f"/api/hosts/{host['id']}"))
    assert (
        detail["runtime_version"] == "4.9.4"
        and detail["system"]["os_name"] == "Oracle Linux Server"
    )

    # 4. create application
    application = _ok(
        client.post(
            "/api/applications",
            json={
                "name": "Customer API",
                "code": "customer-api",
                "runtime_type": "PODMAN",
                "default_port": 8080,
                "healthcheck_type": "HTTP",
                "healthcheck_url": "/",
                "healthcheck_port": 8080,
                "allow_hooks": True,
                "allowed_environments": ["DEV", "PROD"],
            },
        ),
        201,
    )

    # 5. upload + validate + release (v1.0.0 and v1.1.0)
    v1 = build_example_package(example_dir, "podman-app", "1.0.0", tmp_path, secrets=None)
    pkg = _ok(upload_package(client, v1.output_path, release_notes="first"), 201)
    assert (
        pkg["status"] == "VALID"
        and pkg["version_id"]
        and pkg["checksum_sha256"] == v1.checksum_sha256
    )
    v2 = build_example_package(example_dir, "podman-app", "1.1.0", tmp_path, secrets=None)
    _ok(upload_package(client, v2.output_path), 201)
    versions = _ok(client.get(f"/api/applications/{application['id']}/versions"))
    assert [v["version"] for v in versions] == ["1.1.0", "1.0.0"]
    version1 = next(v for v in versions if v["version"] == "1.0.0")
    version2 = next(v for v in versions if v["version"] == "1.1.0")

    # 6. pre-flight
    pf = _ok(
        client.post(
            "/api/deployments/preflight",
            json={
                "application_id": application["id"],
                "version_id": version1["id"],
                "host_ids": [host["id"]],
            },
        )
    )
    assert pf["ok"], pf
    assert {c["name"] for c in pf["hosts"][0]["checks"]} >= {
        "ssh",
        "runtime",
        "disk",
        "memory",
        "package",
        "ports",
    }

    # 7. deploy 1.0.0 (DEV: no confirmation needed)
    batch = _ok(
        client.post(
            "/api/deployments",
            json={
                "application_id": application["id"],
                "version_id": version1["id"],
                "host_ids": [host["id"]],
                "reason": "initial",
            },
        ),
        202,
    )
    dep = _wait_deployment(client, batch["deployments"][0]["id"])
    assert dep["status"] == "SUCCESS", dep
    assert [s["status"] for s in dep["steps"]].count("SUCCESS") == len(dep["steps"])
    assert dep["timeline"][-1]["state"] == "SUCCESS"
    log = client.get(f"/api/deployments/{dep['id']}/log")
    assert log.status_code == 200 and b"Transfer package" in log.data

    # 8. status / health / logs / version
    st = _wait_operation(
        client,
        _ok(
            client.post(
                f"/api/applications/{application['id']}/status", json={"host_id": host["id"]}
            ),
            (200, 202),
        ),
    )
    assert (
        st["result"]["state"] == "RUNNING"
        and st["result"]["version"] == "1.0.0"
        and not st["result"]["drift"]["detected"]
    )
    hl = _wait_operation(
        client,
        _ok(
            client.post(
                f"/api/applications/{application['id']}/health", json={"host_id": host["id"]}
            ),
            (200, 202),
        ),
    )
    assert hl["result"]["status"] == "HEALTHY"
    lg = _wait_operation(
        client,
        _ok(
            client.post(
                f"/api/applications/{application['id']}/logs",
                json={"host_id": host["id"], "parameters": {"lines": 20}},
            ),
            (200, 202),
        ),
    )
    assert lg["result"]["count"] >= 1
    dl = client.get(f"/api/operations/{lg['id']}/download")
    assert dl.status_code == 200 and dl.mimetype == "text/plain"

    # 9. stop / start / restart
    stop = _wait_operation(
        client,
        _ok(
            client.post(
                f"/api/applications/{application['id']}/stop", json={"host_id": host["id"]}
            ),
            (200, 202),
        ),
    )
    assert stop["result_code"] == "STOPPED"
    inst = _ok(client.get(f"/api/applications/{application['id']}/instances"))[0]
    assert inst["desired"]["state"] == "STOPPED" and inst["actual"]["state"] == "STOPPED"
    start = _wait_operation(
        client,
        _ok(
            client.post(
                f"/api/applications/{application['id']}/start", json={"host_id": host["id"]}
            ),
            (200, 202),
        ),
    )
    assert start["result_code"] == "STARTED"
    restart = _wait_operation(
        client,
        _ok(
            client.post(
                f"/api/applications/{application['id']}/restart", json={"host_id": host["id"]}
            ),
            (200, 202),
        ),
    )
    assert restart["status"] == "SUCCESS"

    # 10. deploy 1.1.0 then rollback to 1.0.0
    batch2 = _ok(
        client.post(
            "/api/deployments",
            json={
                "application_id": application["id"],
                "version_id": version2["id"],
                "host_ids": [host["id"]],
                "reason": "upgrade",
            },
        ),
        202,
    )
    dep2 = _wait_deployment(client, batch2["deployments"][0]["id"])
    assert dep2["status"] == "SUCCESS" and dep2["previous_version"] == "1.0.0"
    inst = _ok(client.get(f"/api/applications/{application['id']}/instances"))[0]
    assert inst["current_version"] == "1.1.0" and inst["previous_version"] == "1.0.0"
    rb = _ok(
        client.post(
            f"/api/applications/{application['id']}/rollback",
            json={"host_id": host["id"], "reason": "regression"},
        ),
        202,
    )
    rb = _wait_deployment(client, rb["id"])
    assert rb["kind"] == "ROLLBACK" and rb["status"] == "SUCCESS" and rb["version"] == "1.0.0"
    inst = _ok(client.get(f"/api/applications/{application['id']}/instances"))[0]
    assert inst["current_version"] == "1.0.0" and inst["actual"]["state"] == "RUNNING"

    # 11. dashboard, audit, export
    dash = _ok(client.get("/api/dashboard"))
    assert dash["applications"]["running"] == 1 and dash["deployments"]["today"]["success"] == 3
    audit = _ok(client.get("/api/audit?per_page=200"))
    actions = {a["action"] for a in audit}
    assert {
        "USER_LOGIN",
        "HOST_CREATED",
        "CREDENTIAL_CHANGED",
        "HOST_KEY_APPROVED",
        "APPLICATION_CREATED",
        "PACKAGE_UPLOADED",
        "VERSION_RELEASED",
        "DEPLOYMENT_STARTED",
        "DEPLOYMENT_COMPLETED",
        "APPLICATION_STOPPED",
        "APPLICATION_STARTED",
        "APPLICATION_RESTARTED",
        "ROLLBACK_STARTED",
        "ROLLBACK_COMPLETED",
    } <= actions
    csv = client.get("/api/audit/export?format=csv")
    assert csv.status_code == 200 and b"DEPLOYMENT_COMPLETED" in csv.data
    # web pages render with real data
    for path in (
        f"/hosts/{host['id']}",
        f"/applications/{application['id']}",
        f"/deployments/{dep['id']}",
        f"/operations/{st['id']}",
        "/monitoring/health",
        "/releases",
    ):
        assert client.get(path).status_code == 200, path
    # logout
    _ok(client.post("/api/auth/logout"))
    assert client.get("/api/auth/me").status_code == 401


def test_prod_deployment_with_approval_workflow(
    app, fake_ssh, users, example_dir, tmp_path, prod_operator_client, admin_client
):
    from app.services.settings_service import get_settings_service
    from tests.conftest import make_application, make_host

    make_host(name="prod-app-01", env="PROD")
    application = make_application()
    v1 = build_example_package(example_dir, "podman-app", "1.0.0", tmp_path, secrets=None)
    pkg = _ok(upload_package(admin_client, v1.output_path), 201)
    get_settings_service().set("SCARLET_PROD_REQUIRE_APPROVAL", True)
    host = _ok(admin_client.get("/api/hosts?environment=PROD"))[0]
    batch = _ok(
        prod_operator_client.post(
            "/api/deployments",
            json={
                "application_id": application.id,
                "version_id": pkg["version_id"],
                "host_ids": [host["id"]],
                "reason": "CHG-42",
                "confirmation": "DEPLOY TO PROD",
            },
        ),
        202,
    )
    dep = batch["deployments"][0]
    assert dep["status"] == "PENDING_APPROVAL"
    # requester cannot approve own deployment
    r = prod_operator_client.post(f"/api/deployments/{dep['id']}/approve", json={"comment": "self"})
    assert r.status_code == 403
    # admin approves -> executes
    approved = _ok(
        admin_client.post(f"/api/deployments/{dep['id']}/approve", json={"comment": "reviewed"})
    )
    final = _wait_deployment(admin_client, approved["id"])
    assert final["status"] == "SUCCESS", final
    assert (
        final["approvals"][0]["status"] == "APPROVED"
        and final["approvals"][0]["decided_by"] == "admin"
    )
