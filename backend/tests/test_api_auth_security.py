"""Authentication, setup wizard, CSRF, RBAC matrix, security headers."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pkm.security.users import new_setup_token

from .conftest import API, PASSWORD, complete_setup, login


# ------------------------------------------------------------------ public / setup
def test_system_info_and_setup_status(client):
    info = client.get(f"{API}/system/info").json()
    assert info["setupRequired"] and info["mode"] == "demo" and info["languages"] == ["it", "en"]
    st = client.get(f"{API}/setup/status").json()
    assert st == {"setupRequired": True, "tokenIssued": True, "mode": "demo"}


def test_setup_requires_token(client, ctx):
    body = {"admin": {"username": "admin", "password": PASSWORD}}
    r = client.post(f"{API}/setup/complete", json=body)
    assert r.status_code == 403 and r.json()["error"]["params"]["reason"] == "setup_token"
    r = client.post(f"{API}/setup/complete", json=body, headers={"X-Setup-Token": "wrong"})
    assert r.status_code == 403


def test_setup_wizard_flow(client, ctx):
    token = new_setup_token(ctx.db)
    h = {"X-Setup-Token": token}
    assert client.post(f"{API}/setup/verify-token", headers=h).json() == {"ok": True}
    sc = client.get(f"{API}/setup/system-check", headers=h).json()
    assert {c["id"] for c in sc["checks"]} >= {"os", "arch", "python", "data_dir", "disk_space", "tls", "mode"}
    assert client.post(f"{API}/setup/test-kubernetes", json={}, headers=h).json()["connected"]
    assert client.post(f"{API}/setup/test-podman", json={}, headers=h).json()["connected"]
    assert client.post(f"{API}/setup/test-prometheus", json={}, headers=h).json() == {"ok": False, "skipped": True}
    r = client.post(f"{API}/setup/test-prometheus", json={"prometheus_url": "ftp://x"}, headers=h).json()
    assert r["ok"] is False and r["error"]["code"] == "validation_failed"
    r = client.post(f"{API}/setup/test-prometheus", json={"prometheus_url": "http://127.0.0.1:1"}, headers=h).json()
    assert r["ok"] is False and r["error"]["code"] == "metrics_unavailable"
    weak = client.post(f"{API}/setup/complete", headers=h, json={"admin": {"username": "admin", "password": "weak"}})
    assert weak.status_code == 422 and "too_short" in weak.json()["error"]["params"]["problems"]
    r = client.post(f"{API}/setup/complete", headers=h, json={
        "admin": {"username": "admin", "password": PASSWORD}, "language": "en",
        "monitoring": {"prometheus_url": "http://prom:9090"}, "backup_retention_count": 5,
        "kubernetes": {"kubeconfig": "/ignored/in/demo"}})
    assert r.status_code == 200 and r.json()["user"]["language"] == "en"
    assert ctx.settings.monitoring.prometheus_url == "http://prom:9090" and ctx.settings.backup.retention_count == 5
    # after setup: everything is refused, token is gone
    r = client.post(f"{API}/setup/verify-token", headers=h)
    assert r.status_code == 409 and r.json()["error"]["params"]["reason"] == "setup_done"
    assert client.get(f"{API}/setup/status").json()["setupRequired"] is False
    assert ctx.audit.search(action="setup.completed")["total"] == 1


# ------------------------------------------------------------------ login / logout
def test_unauthenticated(client):
    r = client.get(f"{API}/cluster/overview")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert r.json()["error"]["requestId"]


def test_login_logout(app, client, ctx):
    complete_setup(client, ctx)
    r = client.post(f"{API}/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401 and r.json()["error"]["message"] == "invalid username or password"
    r2 = client.post(f"{API}/auth/login", json={"username": "ghost", "password": "nope"})
    assert r2.json()["error"]["message"] == r.json()["error"]["message"]  # no user enumeration
    c = login(app, "admin")
    me = c.get(f"{API}/auth/me").json()
    assert me["user"]["username"] == "admin" and "users.manage" in me["permissions"] and me["csrfToken"]
    cookie = r.headers.get("set-cookie")
    assert cookie is None
    assert c.post(f"{API}/auth/logout").json() == {"ok": True}
    assert c.get(f"{API}/auth/me").status_code == 401
    assert ctx.audit.search(action="auth.login", result="failure")["total"] == 2


def test_session_cookie_flags(app, client, ctx):
    complete_setup(client, ctx)
    r = client.post(f"{API}/auth/login", json={"username": "admin", "password": PASSWORD})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie


def test_lockout(app, client, ctx):
    complete_setup(client, ctx)
    for _ in range(5):
        client.post(f"{API}/auth/login", json={"username": "admin", "password": "wrong-password"})
    r = client.post(f"{API}/auth/login", json={"username": "admin", "password": PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["params"]["reason"] == "locked"


def test_login_rate_limit(client, ctx):
    codes = [client.post(f"{API}/auth/login", json={"username": f"u{i}", "password": "x"}).status_code for i in range(12)]
    assert codes[-1] == 429
    r = client.post(f"{API}/auth/login", json={"username": "z", "password": "x"})
    assert r.json()["error"]["code"] == "rate_limited" and r.json()["error"]["params"]["retryAfter"] >= 1


def test_change_password_and_sessions(app, admin, ctx):
    other = login(app, "admin")
    assert len(admin.get(f"{API}/auth/sessions").json()["items"]) == 2
    bad = admin.post(f"{API}/auth/change-password", json={"current_password": "x", "new_password": "N3w-Passw0rd-OK"})
    assert bad.status_code == 422
    r = admin.post(f"{API}/auth/change-password", json={"current_password": PASSWORD, "new_password": "N3w-Passw0rd-OK"})
    assert r.status_code == 200
    admin.headers["X-CSRF-Token"] = r.json()["csrfToken"]
    assert other.get(f"{API}/auth/me").status_code == 401  # other sessions revoked
    assert admin.get(f"{API}/auth/me").status_code == 200  # current browser got a fresh session
    third = login(app, "admin", "N3w-Passw0rd-OK")
    assert third.post(f"{API}/auth/sessions/revoke-others").json()["revoked"] == 1
    sessions = third.get(f"{API}/auth/sessions").json()["items"]
    assert len(sessions) == 1 and sessions[0]["current"]
    p = third.patch(f"{API}/auth/me", json={"language": "en", "display_name": "Root"}).json()["user"]
    assert p["language"] == "en" and p["display_name"] == "Root"


def test_must_change_password_blocks(app, admin, ctx):
    r = admin.post(f"{API}/users", json={"username": "newbie", "password": PASSWORD, "role": "operator"})
    assert r.json()["user"]["must_change_password"]
    c = login(app, "newbie")
    r = c.get(f"{API}/cluster/overview")
    assert r.status_code == 403 and r.json()["error"]["params"]["reason"] == "must_change_password"
    assert c.get(f"{API}/auth/me").status_code == 200
    r = c.post(f"{API}/auth/change-password", json={"current_password": PASSWORD, "new_password": "An0ther-Passw0rd"})
    c.headers["X-CSRF-Token"] = r.json()["csrfToken"]
    assert c.get(f"{API}/cluster/overview").status_code == 200


# ------------------------------------------------------------------ CSRF
def test_csrf(app, admin):
    body = {"replicas": 2}
    url = f"{API}/k8s/deployments/production/web-prod/scale"
    no = TestClient(app, cookies=admin.cookies)
    r = no.post(url, json=body)
    assert r.status_code == 403 and r.json()["error"]["params"]["reason"] == "csrf"
    r = no.post(url, json=body, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    r = admin.post(url, json=body, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["params"]["reason"] == "origin"
    assert admin.post(url, json=body, headers={"Origin": "http://testserver"}).status_code == 200
    assert no.get(f"{API}/cluster/overview").status_code == 200  # safe methods need no token


# ------------------------------------------------------------------ RBAC matrix
WEB = f"{API}/k8s/deployments/production/web-prod"
DEPLOY = {"name": "rbac-app", "namespace": "staging", "image": "nginx", "tag": "1.27", "port": 80}
CM_YAML = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: rbac-cm\n  namespace: staging\n"
SECRET_YAML = "apiVersion: v1\nkind: Secret\nmetadata:\n  name: rbac-s\n  namespace: staging\nstringData:\n  a: b\n"
NS_YAML = "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: rbac-ns\n"

CASES = [
    # (method, url, json, viewer, operator, admin) expected "ok" (2xx) or status code
    ("get", f"{API}/cluster/overview", None, "ok", "ok", "ok"),
    ("post", f"{WEB}/scale", {"replicas": 2}, 403, "ok", "ok"),
    ("post", f"{WEB}/restart", None, 403, "ok", "ok"),
    ("post", f"{API}/deploy", DEPLOY, 403, "ok", "ok"),
    ("get", f"{API}/k8s/secrets/production/api-credentials?reveal=true", None, 403, 403, "ok"),
    ("get", f"{API}/users", None, 403, 403, "ok"),
    ("get", f"{API}/audit", None, 403, 403, "ok"),
    ("post", f"{API}/k8s/apply", {"yaml": CM_YAML}, 403, "ok", "ok"),
    ("post", f"{API}/k8s/apply", {"yaml": SECRET_YAML}, 403, 403, "ok"),
    ("post", f"{API}/k8s/apply", {"yaml": NS_YAML}, 403, 403, "ok"),
    ("delete", f"{API}/k8s/configmaps/production/web-config?confirm=web-config", None, 403, 403, "ok"),
    ("post", f"{API}/k8s/nodes/_/node-02/cordon", None, 403, 403, "ok"),
    ("post", f"{API}/k8s/nodes/_/node-02/drain", {"confirm": "node-02", "timeout_seconds": 30}, 403, 403, "ok"),
    ("get", f"{API}/settings", None, 403, "ok", "ok"),
    ("put", f"{API}/settings/logging", {"level": "INFO"}, 403, 403, "ok"),
    ("get", f"{API}/backups", None, 403, "ok", "ok"),
    ("post", f"{API}/backups", {}, 403, 403, "ok"),
    ("post", f"{API}/podman/containers/pg-reporting/action", {"action": "restart"}, 403, "ok", "ok"),
    ("post", f"{API}/podman/images/pull", {"reference": "docker.io/library/busybox:1.36"}, 403, 403, "ok"),
    ("post", f"{API}/maintenance/cache/clear", None, 403, 403, "ok"),
    ("post", f"{API}/images/inspect", {"image": "nginx:1.27"}, 403, "ok", "ok"),
]


@pytest.mark.parametrize("method,url,body,v,o,a", CASES, ids=[f"{c[0]} {c[1].split('/api/v1')[1][:50]}" for c in CASES])
def test_rbac_matrix(viewer, operator, admin, method, url, body, v, o, a):
    for client, expected in ((viewer, v), (operator, o), (admin, a)):
        kw = {"json": body} if body is not None else {}
        r = getattr(client, method)(url, **kw)
        if expected == "ok":
            assert r.status_code < 300, (client, url, r.text)
        else:
            assert r.status_code == expected, (url, r.status_code, r.text)
            assert r.json()["error"]["code"] == "forbidden"


def test_viewer_cannot_read_logs(viewer, admin):
    from .conftest import pod_name

    p = pod_name(admin, "production", "web-prod")
    assert viewer.get(f"{API}/k8s/pods/production/{p}/logs").status_code == 403
    assert viewer.get(f"{API}/podman/containers/edge-proxy/logs").status_code == 403


def test_denied_access_is_audited(viewer, admin, ctx):
    viewer.post(f"{WEB}/scale", json={"replicas": 2})
    viewer.get(f"{API}/k8s/secrets/production/api-credentials?reveal=true")
    assert ctx.audit.search(result="denied", username="view")["total"] == 2


def test_operator_can_delete_pods_only(operator, admin):
    from .conftest import pod_name

    p = pod_name(admin, "production", "web-prod")
    assert operator.delete(f"{API}/k8s/pods/production/{p}").status_code == 200
    assert operator.delete(f"{API}/k8s/services/production/web-prod?confirm=web-prod").status_code == 403


def test_roles_endpoint(viewer):
    r = viewer.get(f"{API}/rbac/roles").json()
    assert {x["id"] for x in r["roles"]} == {"admin", "operator", "viewer"}
    assert "users.manage" in r["permissions"]


# ------------------------------------------------------------------ headers / errors
def test_security_headers(client):
    r = client.get(f"{API}/system/info")
    h = r.headers
    assert "default-src 'self'" in h["content-security-policy"] and h["x-frame-options"] == "DENY"
    assert h["x-pkm-mode"] == "demo" and h["x-content-type-options"] == "nosniff" and h["cache-control"] == "no-store"
    assert h["x-request-id"]
    r = client.get(f"{API}/system/info", headers={"X-Request-ID": "my-request-0001"})
    assert r.headers["x-request-id"] == "my-request-0001"
    r = client.get(f"{API}/system/info", headers={"X-Request-ID": "bad id!"})
    assert r.headers["x-request-id"] != "bad id!"


def test_unknown_endpoint_json_404(admin):
    r = admin.get(f"{API}/does/not/exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = admin.get(f"{API}/k8s/widgets")
    assert r.status_code == 404 and r.json()["error"]["params"]["kind"] == "widgets"


def test_validation_error_format(admin):
    r = admin.post(f"{WEB}/scale", json={"replicas": -1})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_failed" and err["params"]["errors"][0]["field"] == "replicas"


def test_healthz_readyz_and_root(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json()["status"] == "ok"
    assert "web UI is not built" in client.get("/").json()["message"]
    assert client.get(f"{API}/openapi.json").json()["info"]["version"] == "1.0.0"
    assert client.get("/api/docs").status_code == 200  # development only


def test_api_rate_limit(tmp_path):
    from pkm.main import create_app

    from .conftest import make_settings

    app = create_app(make_settings(tmp_path, rate_limit={"api_per_minute": 30, "login_per_minute": 10}),
                     start_background=False)
    with TestClient(app) as c:
        codes = [c.get(f"{API}/system/info").status_code for _ in range(32)]
    assert codes[29] == 200 and codes[-1] == 429


def test_static_spa(tmp_path):
    from pkm.main import create_app

    from .conftest import make_settings

    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>pkm</html>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = create_app(make_settings(tmp_path, server={"static_dir": str(static)}), start_background=False)
    with TestClient(app) as c:
        assert c.get("/").text == "<html>pkm</html>"
        assert c.get("/cluster/nodes").text == "<html>pkm</html>"  # SPA fallback
        r = c.get("/assets/app.js")
        assert r.text == "console.log(1)" and "immutable" in r.headers["cache-control"]
        assert c.get("/../pkm.db").text == "<html>pkm</html>"
        assert c.get(f"{API}/nope").status_code == 404
