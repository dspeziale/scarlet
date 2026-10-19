"""LIVE mode failure handling and the live Kubernetes / Podman clients against local fake servers."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from pkm.config import KubernetesConfig, PodmanConfig
from pkm.errors import (
    K8sAuthFailed,
    K8sForbidden,
    K8sNotConfigured,
    K8sNotFound,
    K8sTimeout,
    K8sUnavailable,
    PodmanError,
    PodmanNotConfigured,
    PodmanNotFound,
    PodmanUnavailable,
)
from pkm.k8s.kinds import KINDS
from pkm.k8s.live import LiveKubernetes
from pkm.main import create_app
from pkm.podman.client import LivePodman

from .conftest import API, complete_setup, login, make_settings


def kubeconfig(tmp_path: Path, server: str, name: str = "kc", context: str = "test") -> str:
    data = {"apiVersion": "v1", "kind": "Config", "current-context": context,
            "clusters": [{"name": "c", "cluster": {"server": server, "insecure-skip-tls-verify": True}}],
            "users": [{"name": "u", "user": {"token": "secret-token"}}],
            "contexts": [{"name": context, "context": {"cluster": "c", "user": "u"}}]}
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(p)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_app(tmp_path):
    def build(**k8s):
        port = free_port()  # nothing listens here: Podman is offline too
        s = make_settings(tmp_path, mode="live", environment="production",
                          kubernetes={"connect_timeout": 1, "request_timeout": 2, **k8s},
                          podman={"url": f"http://127.0.0.1:{port}", "timeout": 2})
        return create_app(s, start_background=False)

    return build


def setup_admin(app):
    c = TestClient(app)
    c.__enter__()
    complete_setup(c, app.state.ctx)
    return c, login(app, "admin")


# ------------------------------------------------------------------ LIVE mode, cluster offline
def test_kubernetes_offline(tmp_path, live_app):
    app = live_app(kubeconfig=kubeconfig(tmp_path, f"https://127.0.0.1:{free_port()}"))
    anon, admin = setup_admin(app)
    try:
        r = admin.get(f"{API}/cluster/overview")
        assert r.status_code in (503, 504)
        err = r.json()["error"]
        assert err["code"] in ("k8s_unavailable", "k8s_timeout") and err["message"] and err["details"]
        st = admin.get(f"{API}/system/status").json()
        assert st["mode"] == "live" and st["kubernetes"]["connected"] is False and st["kubernetes"]["error"]["code"]
        assert st["podman"]["connected"] is False and st["podman"]["error"]["code"] == "podman_unavailable"
        h = admin.get(f"{API}/health").json()
        by = {c["id"]: c for c in h["checks"]}
        assert by["kubernetes"]["status"] == "unhealthy" and by["podman"]["status"] == "unhealthy"
        assert by["metrics_server"]["message"] == "kubernetes_unavailable"
        assert h["status"] == "unhealthy"
        # the application keeps working for everything that does not need the cluster
        assert admin.get(f"{API}/users").status_code == 200 and admin.get(f"{API}/audit").status_code == 200
        r = admin.get(f"{API}/podman/containers")
        assert r.status_code == 503 and r.json()["error"]["code"] == "podman_unavailable"
        # the monitor raises a CRITICAL notification for the unreachable cluster
        app.state.ctx.monitor_once()
        reasons = {n["reason"] for n in admin.get(f"{API}/notifications").json()["items"]}
        assert {"KubernetesUnreachable", "PodmanUnreachable"} <= reasons
        assert admin.get(f"{API}/search", params={"q": "web"}).json()["items"] == []
        assert admin.get(f"{API}/monitoring/sources").json()["metricsServer"] is False
        assert admin.get("/readyz").status_code == 200
    finally:
        anon.__exit__(None, None, None)


def test_kubernetes_timeout(tmp_path):
    # a listening socket that never answers: the read timeout must fire, no infinite wait
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    port = srv.getsockname()[1]
    try:
        prov = LiveKubernetes(KubernetesConfig(kubeconfig=kubeconfig(tmp_path, f"http://127.0.0.1:{port}"),
                                               connect_timeout=1, request_timeout=1))
        with pytest.raises(K8sTimeout):
            prov.list(KINDS["pods"])
        info = prov.info()
        assert info["connected"] is False and info["error"]["code"] == "k8s_timeout"
    finally:
        srv.close()


def test_kubernetes_not_configured(tmp_path, live_app):
    app = live_app()
    anon, admin = setup_admin(app)
    try:
        r = admin.get(f"{API}/cluster/overview")
        assert r.status_code == 503 and r.json()["error"]["code"] == "k8s_not_configured"
        assert r.json()["error"]["params"]["reason"] == "no_kubeconfig"
    finally:
        anon.__exit__(None, None, None)
    assert LiveKubernetes(KubernetesConfig(enabled=False)).info()["error"]["code"] == "k8s_not_configured"
    prov = LiveKubernetes(KubernetesConfig(kubeconfig=str(tmp_path / "missing")))
    assert prov.info()["error"]["code"] == "k8s_not_configured" and not prov.configured
    with pytest.raises(K8sNotConfigured):
        prov.list(KINDS["pods"])
    bad = tmp_path / "garbage"
    bad.write_text(": not yaml [", encoding="utf-8")
    assert LiveKubernetes(KubernetesConfig(kubeconfig=str(bad))).info()["error"]["code"] == "k8s_not_configured"


def test_invalid_context(tmp_path):
    prov = LiveKubernetes(KubernetesConfig(kubeconfig=kubeconfig(tmp_path, "https://127.0.0.1:1"), context="other"))
    err = prov.info()["error"]
    assert err["code"] == "k8s_not_configured" and err["params"]["available"] == ["test"]


def test_settings_change_reconnects(tmp_path, live_app):
    app = live_app()
    anon, admin = setup_admin(app)
    try:
        server = FakeK8s()
        try:
            r = admin.put(f"{API}/settings/kubernetes", json={"kubeconfig": kubeconfig(tmp_path, server.url)})
            assert r.status_code == 200
            assert admin.get(f"{API}/system/status").json()["kubernetes"]["connected"]
            assert admin.get(f"{API}/k8s/pods").json()["count"] == 1
        finally:
            server.stop()
    finally:
        anon.__exit__(None, None, None)


def test_kubernetes_forbidden_mapped(admin, ctx, monkeypatch):
    def deny(*a, **k):
        raise K8sForbidden("the Kubernetes account used by Scarlet is not allowed to do this", params={"status": 403})

    monkeypatch.setattr(ctx.k8s.provider, "list", deny)
    ctx.k8s.invalidate()
    r = admin.get(f"{API}/k8s/pods")
    assert r.status_code == 403 and r.json()["error"]["code"] == "k8s_forbidden"
    # partial snapshot: the dashboard reports which kinds could not be read instead of failing
    r = admin.get(f"{API}/cluster/overview")
    assert r.status_code == 200 and len(r.json()["partial"]) > 5


def test_pod_deleted_during_log_stream(admin, ctx, monkeypatch):
    from .conftest import pod_name

    p = pod_name(admin, "production", "web-prod")
    ctx.k8s.delete("pods", p, "production")
    r = admin.get(f"{API}/k8s/pods/production/{p}/logs/stream")
    assert r.status_code == 404 and r.json()["error"]["code"] == "k8s_not_found"
    r = admin.get(f"{API}/k8s/pods/production/{p}/logs")
    assert r.status_code == 404


def test_log_stream_concurrency_limit(admin, ctx):
    from .conftest import pod_name

    ctx.log_streams._value = 0  # all slots taken
    p = pod_name(admin, "production", "web-prod")
    r = admin.get(f"{API}/k8s/pods/production/{p}/logs/stream")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


@pytest.mark.parametrize("text,needle", [
    ("kind: ConfigMap\nmetadata:\n  name: a\n", "apiVersion"),
    ("apiVersion: v2\nkind: ConfigMap\nmetadata:\n  name: a\n", "not supported"),
    ("apiVersion: v1\nkind: Node\nmetadata:\n  name: a\n  namespace: x\n", "cluster-scoped"),
    ("- a\n- b\n", "not a mapping"),
    ("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: Bad_Name\n", "not a valid Kubernetes name"),
])
def test_malformed_resources(admin, text, needle):
    r = admin.post(f"{API}/k8s/apply", json={"yaml": text})
    assert r.status_code in (422, 501) and needle in r.json()["error"]["message"]


def test_podman_offline_and_unix_socket(tmp_path):
    p = LivePodman(PodmanConfig(url=f"http://127.0.0.1:{free_port()}", timeout=1))
    with pytest.raises(PodmanUnavailable):
        p.list_containers()
    assert p.info()["error"]["code"] == "podman_unavailable"
    p.close()
    assert LivePodman(PodmanConfig(enabled=False)).info()["error"]["code"] == "podman_not_configured"
    assert LivePodman(PodmanConfig(url="ftp://x")).info()["error"]["code"] == "podman_not_configured"
    with pytest.raises(PodmanNotConfigured):
        LivePodman(PodmanConfig(enabled=False)).list_images()
    if hasattr(socket, "AF_UNIX") and not __import__("sys").platform.startswith("win"):
        u = LivePodman(PodmanConfig(url=f"unix://{tmp_path}/missing.sock", timeout=1))
        assert u.info()["error"]["code"] == "podman_unavailable"


# ------------------------------------------------------------------ fake Kubernetes API server
POD = {"metadata": {"name": "p1", "namespace": "default", "uid": "u1"}, "spec": {"containers": [{"name": "c"}]},
       "status": {"phase": "Running"}}


class FakeK8s:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict, bytes]] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append((self.command, self.path, dict(self.headers), body))
                path = self.path.split("?")[0]
                if path == "/version":
                    return self._send(200, {"gitVersion": "v1.30.0", "major": "1", "minor": "30", "platform": "linux/amd64"})
                if path == "/api/v1/pods" or path == "/api/v1/namespaces/default/pods":
                    return self._send(200, {"items": [POD]})
                if path == "/api/v1/namespaces/default/pods/p1":
                    if self.command == "DELETE":
                        return self._send(200, {"kind": "Status", "status": "Success"})
                    return self._send(200, POD)
                if path == "/api/v1/namespaces/default/pods/p1/log":
                    if "follow=true" in self.path:
                        return self._send(200, b"2026-01-01T00:00:01Z one\n2026-01-01T00:00:02Z two\n", "text/plain")
                    return self._send(200, b'{"json": "line"}\nplain\n', "text/plain")
                if path == "/api/v1/namespaces/default/pods/p1/eviction":
                    if b"policy/v1beta1" in body:
                        return self._send(201, {})
                    return self._send(400, {"message": "no kind Eviction in policy/v1", "reason": "BadRequest"})
                if path == "/apis/apps/v1/namespaces/default/deployments/web":
                    if self.command == "PATCH":
                        return self._send(200, {"metadata": {"name": "web"}, "kind": "Deployment"})
                    return self._send(403, {"message": 'deployments.apps "web" is forbidden', "reason": "Forbidden"})
                if path == "/api/v1/namespaces/default/configmaps":
                    return self._send(201, json.loads(body))
                if path == "/api/v1/secrets":
                    return self._send(401, {"message": "Unauthorized"})
                if path == "/apis/metrics.k8s.io/v1beta1/nodes":
                    return self._send(404, {"message": "the server could not find the requested resource"})
                if path == "/apis/metrics.k8s.io/v1beta1/pods":
                    return self._send(200, {"items": [{"metadata": {"name": "p1"}}]})
                if path == "/api/v1/nodes":
                    return self._send(200, b"not json")
                return self._send(404, {"message": f"{path} not found", "reason": "NotFound"})

            do_GET = do_POST = do_PATCH = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self.server.shutdown()


@pytest.fixture
def fake_k8s():
    s = FakeK8s()
    yield s
    s.stop()


def test_live_client_against_fake_api(tmp_path, fake_k8s):
    prov = LiveKubernetes(KubernetesConfig(kubeconfig=kubeconfig(tmp_path, fake_k8s.url), request_timeout=5))
    info = prov.info()
    assert info["connected"] and info["version"]["gitVersion"] == "v1.30.0" and info["context"] == "test"
    assert prov.info()["connected"]  # cached version
    pods = prov.list(KINDS["pods"], None, label_selector="app=x")
    assert pods[0]["kind"] == "Pod" and pods[0]["apiVersion"] == "v1"
    _, path, headers, _ = fake_k8s.requests[-1]
    assert path == "/api/v1/pods?labelSelector=app%3Dx" and headers["Authorization"] == "Bearer secret-token"
    assert prov.get(KINDS["pods"], "p1", "default")["kind"] == "Pod"
    # JSON log lines are returned verbatim (not json-decoded)
    assert prov.pod_logs("p1", "default", tail_lines=10, timestamps=True) == '{"json": "line"}\nplain\n'
    assert "tailLines=10" in fake_k8s.requests[-1][1] and "timestamps=true" in fake_k8s.requests[-1][1]
    assert list(prov.stream_pod_logs("p1", "default", tail_lines=5)) == ["2026-01-01T00:00:01Z one",
                                                                          "2026-01-01T00:00:02Z two"]
    prov.evict("p1", "default")  # falls back to policy/v1beta1
    assert b"policy/v1beta1" in fake_k8s.requests[-1][3]
    with pytest.raises(K8sForbidden) as e:
        prov.get(KINDS["deployments"], "web", "default")
    assert e.value.params["reason"] == "Forbidden" and "forbidden" in e.value.details
    res = prov.patch(KINDS["deployments"], "web", "default", {"spec": {"replicas": 2}}, dry_run=True)
    assert res["kind"] == "Deployment"
    m, p, h, _ = fake_k8s.requests[-1]
    assert m == "PATCH" and "dryRun=All" in p and h["Content-Type"] == "application/merge-patch+json"
    prov.patch(KINDS["deployments"], "web", "default", [{"op": "replace", "path": "/spec", "value": {}}], patch_type="json")
    assert fake_k8s.requests[-1][2]["Content-Type"] == "application/json-patch+json"
    prov.apply({"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "web", "namespace": "default"}},
               force=True)
    m, p, h, _ = fake_k8s.requests[-1]
    assert h["Content-Type"] == "application/apply-patch+yaml" and "fieldManager=pkm" in p and "force=true" in p
    cm = prov.create({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "c", "namespace": "default"}})
    assert cm["metadata"]["name"] == "c"
    assert prov.delete(KINDS["pods"], "p1", "default")["status"] == "Success"
    assert json.loads(fake_k8s.requests[-1][3])["propagationPolicy"] == "Background"
    with pytest.raises(K8sAuthFailed):
        prov.list(KINDS["secrets"])
    with pytest.raises(K8sNotFound):
        prov.get(KINDS["pods"], "ghost", "default")
    with pytest.raises(K8sUnavailable, match="unexpected response"):
        prov.list(KINDS["nodes"])
    assert prov.node_metrics() is None  # metrics-server missing
    assert prov.pod_metrics() == [{"metadata": {"name": "p1"}}]
    assert prov.pod_metrics("default") is None  # namespaced metrics path answers 404 on the fake
    prov.close()


def test_live_client_eviction_of_missing_pod(tmp_path, fake_k8s):
    prov = LiveKubernetes(KubernetesConfig(kubeconfig=kubeconfig(tmp_path, fake_k8s.url)))
    with pytest.raises(K8sNotFound):
        prov.evict("ghost", "default")


def test_live_app_with_fake_api(tmp_path, fake_k8s, live_app):
    app = live_app(kubeconfig=kubeconfig(tmp_path, fake_k8s.url), request_timeout=5)
    anon, admin = setup_admin(app)
    try:
        st = admin.get(f"{API}/system/status").json()
        assert st["kubernetes"]["connected"] and st["kubernetes"]["version"] == "v1.30.0"
        assert st["kubernetes"]["server"] == fake_k8s.url
        assert admin.get(f"{API}/k8s/pods").json()["items"][0]["name"] == "p1"
        r = admin.get(f"{API}/k8s/ingresses")
        assert r.status_code == 501 and r.json()["error"]["code"] == "k8s_unsupported"
        r = admin.get(f"{API}/cluster/overview")
        # nodes answer garbage: a readable 503, never a bare 500
        assert r.status_code == 503 and r.json()["error"]["code"] == "k8s_unavailable"
    finally:
        anon.__exit__(None, None, None)


# ------------------------------------------------------------------ fake Podman API server
class FakePodman:
    def __init__(self) -> None:
        import struct

        frame = lambda s, d: bytes([s, 0, 0, 0]) + struct.pack(">I", len(d)) + d  # noqa: E731

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                path = self.path.split("?")[0].replace("/v4.0.0/libpod", "")
                if path == "/info":
                    return self._send(200, {"host": {"os": "linux", "arch": "amd64", "security": {"rootless": True}},
                                            "store": {"graphDriverName": "overlay", "imageStore": {"number": 1}},
                                            "registries": {"search": ["docker.io"]}})
                if path == "/version":
                    return self._send(200, {"Version": "5.2.0", "ApiVersion": "5.2.0"})
                if path == "/containers/json":
                    return self._send(200, [{"Id": "a" * 64, "Names": ["web"], "State": "running", "Image": "nginx"}])
                if path == "/containers/web/json":
                    return self._send(200, {"Name": "web", "Config": {"Tty": False}})
                if path == "/containers/web/logs":
                    return self._send(200, frame(1, b"hello\n") + frame(2, b"oops\n"))
                if path in ("/containers/web/stop", "/containers/web/start", "/containers/web/restart"):
                    return self._send(204, b"")
                if path == "/containers/web" and self.command == "DELETE":
                    return self._send(409, {"cause": "running", "message": "container is running"})
                if path == "/images/json":
                    return self._send(200, [{"Id": "sha256:" + "b" * 64, "RepoTags": ["nginx:1"], "Size": 10}])
                if path == "/images/pull":
                    if "bad" in self.path:
                        return self._send(200, b'{"error": "manifest unknown"}\n')
                    return self._send(200, b'{"stream": "pulling"}\n{"id": "abc", "images": ["abc"]}\n')
                if path.startswith("/images/") and self.command == "DELETE":
                    return self._send(200, [{"Deleted": "x"}])
                if path.startswith("/images/") and path.endswith("/json"):
                    return self._send(200, {"Id": "x", "Config": {}})
                if path == "/containers/stats":
                    return self._send(200, {"Stats": [{"ContainerID": "a" * 64, "Name": "web", "CPU": 1.5}]})
                if path == "/containers/broken/json":
                    return self._send(500, b"<<not json>>")
                return self._send(404, {"message": "no such container"})

            do_GET = do_POST = do_DELETE = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def test_live_podman_against_fake_api():
    fake = FakePodman()
    try:
        p = LivePodman(PodmanConfig(url=fake.url, timeout=5))
        info = p.info()
        assert info["connected"] and info["version"] == "5.2.0" and info["rootless"] and info["images"] == 1
        assert p.list_containers()[0]["name"] == "web"
        assert p.container_logs("web", tail=10, timestamps=False) == ["hello", "oops"]
        for a in ("start", "stop", "restart"):
            p.container_action("web", a)
        with pytest.raises(PodmanError):
            p.container_action("web", "kill")
        with pytest.raises(PodmanError) as e:
            p.remove_container("web")
        assert e.value.params["status"] == 409 and e.value.message == "container is running"
        with pytest.raises(PodmanNotFound):
            p.inspect_container("ghost")
        with pytest.raises(PodmanError):
            p.inspect_container("broken")
        assert p.list_images()[0]["tags"] == ["nginx:1"]
        assert p.inspect_image("nginx:1")["Id"] == "x"
        p.remove_image("nginx:1", force=True)
        assert p.pull_image("docker.io/library/nginx:1")["id"] == "abc"
        with pytest.raises(PodmanError, match="manifest unknown"):
            p.pull_image("docker.io/library/bad:1")
        assert p.stats()[0]["cpuPercent"] == 1.5
        p.close()
    finally:
        fake.server.shutdown()


def test_setup_wizard_live_probes(tmp_path, fake_k8s, live_app):
    from pkm.security.users import new_setup_token

    fake_pm = FakePodman()
    app = live_app()
    try:
        with TestClient(app) as c:
            h = {"X-Setup-Token": new_setup_token(app.state.ctx.db)}
            kc = kubeconfig(tmp_path, fake_k8s.url)
            r = c.post(f"{API}/setup/test-kubernetes", headers=h, json={"kubeconfig": kc}).json()
            assert r["connected"] and r["permissions"] == {"nodes": "k8s_unavailable", "pods": "ok",
                                                           "deployments": "k8s_not_found", "events": "k8s_not_found"}
            r = c.post(f"{API}/setup/test-kubernetes", headers=h, json={"kubeconfig": str(tmp_path / "none")}).json()
            assert not r["connected"] and r["error"]["code"] == "k8s_not_configured"
            assert c.post(f"{API}/setup/test-kubernetes", headers=h, json={"enabled": False}).json()["skipped"]
            assert c.post(f"{API}/setup/test-podman", headers=h, json={"url": fake_pm.url}).json()["connected"]
            assert c.post(f"{API}/setup/test-podman", headers=h, json={"enabled": False}).json()["skipped"]
            r = c.post(f"{API}/setup/complete", headers=h, json={
                "admin": {"username": "admin", "password": "Str0ng-Passw0rd!"},
                "kubernetes": {"kubeconfig": kc}, "podman": {"url": fake_pm.url}})
            assert r.status_code == 200
            ctx = app.state.ctx
            assert ctx.settings.kubernetes.kubeconfig == kc and ctx.k8s.info()["connected"]
            assert ctx.podman.info()["connected"]
            admin = login(app, "admin")
            assert admin.get(f"{API}/podman/containers").json()["items"][0]["name"] == "web"
            assert admin.post(f"{API}/images/inspect", json={"image": "Bad Image"}).json()["checks"][0]["status"] == "fail"
    finally:
        fake_pm.server.shutdown()
