"""Deploy wizard manifests, image onboarding (registry inspector), Podman log demux, live client helpers."""

from __future__ import annotations

import json
import struct

import httpx
import pytest
import urllib3
from pydantic import ValidationError

from pkm import images
from pkm.errors import (
    AppError,
    K8sAuthFailed,
    K8sConflict,
    K8sForbidden,
    K8sInvalid,
    K8sNotFound,
    K8sTimeout,
    K8sUnavailable,
)
from pkm.k8s import manifests
from pkm.k8s.live import _safe_server, _UrllibLogStream, map_api_error, map_transport_exception
from pkm.podman.client import _demux, container_summary, image_summary


def spec(**kw):
    base = {"name": "hello", "namespace": "apps", "image": "nginx", "tag": "1.27", "port": 80}
    base.update(kw)
    return manifests.DeploySpec(**base)


# ------------------------------------------------------------------ manifests
def test_generate_minimal():
    docs = manifests.generate(spec(networking={"service_type": "none"}))
    assert [d["kind"] for d in docs] == ["Deployment"]
    dep = docs[0]
    c = dep["spec"]["template"]["spec"]["containers"][0]
    assert c["image"] == "nginx:1.27" and c["imagePullPolicy"] == "IfNotPresent"
    assert dep["spec"]["selector"]["matchLabels"].items() <= dep["spec"]["template"]["metadata"]["labels"].items()
    assert c["resources"] == {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}}
    assert dep["spec"]["strategy"]["type"] == "RollingUpdate"


def test_generate_full():
    s = spec(create_namespace=True, image_pull_secret="regcred", replicas=1, env=[{"name": "A", "value": "1"}],
             storage={"enabled": True, "size": "2Gi", "storage_class": "standard", "mount_path": "/var/data"},
             networking={"service_type": "NodePort", "service_port": 8080, "node_port": 30080,
                         "ingress": {"enabled": True, "host": "app.example.com", "class_name": "nginx", "tls_secret": "tls"}},
             readiness={"type": "http", "path": "/ready"}, liveness={"type": "tcp", "port": 80}, cpu_limit="1")
    docs = manifests.generate(s)
    kinds = [d["kind"] for d in docs]
    assert kinds == ["Namespace", "PersistentVolumeClaim", "Deployment", "Service", "Ingress"]
    dep = docs[2]
    pod = dep["spec"]["template"]["spec"]
    c = pod["containers"][0]
    assert pod["imagePullSecrets"] == [{"name": "regcred"}]
    assert c["readinessProbe"]["httpGet"] == {"path": "/ready", "port": 80}
    assert c["livenessProbe"]["tcpSocket"] == {"port": 80}
    assert c["env"] == [{"name": "A", "value": "1"}]
    assert c["volumeMounts"][0]["mountPath"] == "/var/data"
    assert dep["spec"]["strategy"] == {"type": "Recreate"}
    assert docs[1]["spec"]["storageClassName"] == "standard"
    svc = docs[3]["spec"]
    assert svc["type"] == "NodePort" and svc["ports"][0]["nodePort"] == 30080 and svc["ports"][0]["port"] == 8080
    ing = docs[4]["spec"]
    assert ing["ingressClassName"] == "nginx" and ing["tls"][0]["secretName"] == "tls"
    assert ing["rules"][0]["http"]["paths"][0]["backend"]["service"]["port"]["number"] == 8080
    text = manifests.to_yaml(docs)
    assert text.count("---") == 4 and "kind: Ingress" in text


def test_risks():
    codes = lambda s: {r["code"] for r in manifests.risks(s)}  # noqa: E731
    assert {"single_replica", "no_readiness", "no_liveness"} <= codes(spec())
    assert "zero_replicas" in codes(spec(replicas=0))
    assert "latest_tag" in codes(spec(tag="latest"))
    assert {"no_memory_limit", "no_requests"} <= codes(spec(memory_limit=None, cpu_request=None))
    assert {"rwo_multi_replica", "recreate_strategy"} <= codes(spec(replicas=3, storage={"enabled": True}))
    assert "nodeport_exposed" in codes(spec(networking={"service_type": "NodePort"}))
    assert "loadbalancer_exposed" in codes(spec(networking={"service_type": "LoadBalancer"}))
    assert "ingress_no_tls" in codes(spec(networking={"service_type": "ClusterIP", "ingress": {"enabled": True, "host": "a.b"}}))
    assert "secret_in_env" in codes(spec(env=[{"name": "DB_PASSWORD", "value": "x"}]))
    good = spec(replicas=2, readiness={"type": "http"}, liveness={"type": "http"})
    assert codes(good) == set()
    assert spec(tag="latest").model_dump()["tag"] == "latest"
    assert manifests.generate(spec(tag="latest"))[0]["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"] == "Always"


@pytest.mark.parametrize("kw", [
    {"name": "Bad_Name"}, {"name": "x" * 51}, {"namespace": "NS"}, {"image": "nginx:1.27"}, {"image": "UPPER"},
    {"image": "a@sha256:x"}, {"tag": "bad tag"}, {"image_pull_secret": "Bad!"}, {"cpu_request": "1Gi"},
    {"memory_limit": "lots"}, {"cpu_request": "2", "cpu_limit": "1"}, {"memory_request": "1Gi", "memory_limit": "1Mi"},
    {"port": None}, {"networking": {"service_type": "none", "ingress": {"enabled": True, "host": "a.b"}}},
    {"networking": {"service_type": "ClusterIP", "ingress": {"enabled": True}}},
    {"networking": {"service_type": "ClusterIP", "node_port": 30001}},
    {"port": None, "networking": {"service_type": "none"}, "readiness": {"type": "http"}},
    {"env": [{"name": "A", "value": "1"}, {"name": "A", "value": "2"}]}, {"env": [{"name": "1BAD"}]},
    {"storage": {"enabled": True, "size": "big"}}, {"storage": {"enabled": True, "mount_path": "/"}},
    {"storage": {"enabled": True, "storage_class": "Bad!"}}, {"readiness": {"type": "http", "path": "nope"}},
    {"networking": {"service_type": "ClusterIP", "ingress": {"enabled": True, "host": "bad host"}}},
    {"networking": {"service_type": "ClusterIP", "ingress": {"enabled": True, "host": "a.b", "path": "x"}}},
    {"networking": {"service_type": "ClusterIP", "ingress": {"enabled": True, "host": "a.b", "tls_secret": "B!"}}},
    {"replicas": 51},
])
def test_spec_validation_errors(kw):
    with pytest.raises(ValidationError):
        spec(**kw)


def test_spec_normalisation():
    s = spec(image_pull_secret="", cpu_limit="", storage={"storage_class": ""},
             networking={"service_type": "ClusterIP", "ingress": {"host": " A.Example.COM ", "class_name": ""}})
    assert s.image_pull_secret is None and s.cpu_limit is None and s.storage.storage_class is None
    assert s.networking.ingress.host == "a.example.com" and s.networking.ingress.class_name is None


# ------------------------------------------------------------------ images
CFG = {"architecture": "amd64", "os": "linux", "created": "2026-01-01",
       "config": {"ExposedPorts": {"8080/tcp": {}, "53/udp": {}, "bad": {}}, "User": "",
                  "Env": ["PATH=/bin", "DB_PASSWORD=secret"], "Entrypoint": ["/app"], "Volumes": {"/data": {}},
                  "Healthcheck": {"Test": ["CMD", "true"]}}}


def test_describe_config_and_risks():
    d = images.describe_config(CFG)
    assert d["exposedPorts"] == [{"port": 53, "protocol": "UDP"}, {"port": 8080, "protocol": "TCP"}]
    assert d["runsAsRoot"] and {"name": "DB_PASSWORD", "value": "<hidden>"} in d["env"]
    assert d["volumes"] == ["/data"] and d["healthcheck"] == ["CMD", "true"]
    codes = {r["code"] for r in images.config_risks(d)}
    assert codes == {"runs_as_root", "declares_volumes", "secret_in_image_env"}
    d2 = images.describe_config({"config": {"User": "1001"}})
    assert not d2["runsAsRoot"] and {r["code"] for r in images.config_risks(d2)} == {"no_exposed_ports"}
    assert images.describe_config({"config": {"User": "0:0"}})["runsAsRoot"]


def test_podman_image_config():
    d = images.podman_image_config({"Architecture": "amd64", "Os": "linux", "Config": {"ExposedPorts": {"80/tcp": {}}}})
    assert d["exposedPorts"][0]["port"] == 80
    with pytest.raises(AppError):
        images.podman_image_config({})


def test_demo_inspect():
    r = images.demo_inspect("nginx:1.27")
    assert r["config"]["exposedPorts"] == [{"port": 80, "protocol": "TCP"}] and r["demo"]
    assert {c["id"]: c["status"] for c in images.demo_inspect("x/notfound:1")["checks"]}["tag_exists"] == "fail"
    assert images.demo_inspect("BAD IMAGE")["checks"] == [{"id": "image_format", "status": "fail"}]
    assert any(r["code"] == "latest_tag" for r in images.demo_inspect("registry.example.com/app")["risks"])


_REAL_CLIENT = httpx.Client


def _registry(handler):
    transport = httpx.MockTransport(handler)
    real = _REAL_CLIENT

    def factory(*args, **kwargs):
        kwargs.pop("verify", None)
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    return factory


INDEX = {"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": [
    {"digest": "sha256:arm", "platform": {"os": "linux", "architecture": "arm64"}},
    {"digest": "sha256:amd", "platform": {"os": "linux", "architecture": "amd64"}}]}
MANIFEST = {"mediaType": "application/vnd.oci.image.manifest.v1+json", "config": {"digest": "sha256:cfg"},
            "layers": [{"size": 100}, {"size": 50}]}


def test_registry_inspector_index_with_token(monkeypatch):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.url.host == "auth.example.com":
            assert req.url.params["scope"] == "repository:library/nginx:pull"
            return httpx.Response(200, json={"token": "T"})
        if "Authorization" not in req.headers:
            return httpx.Response(401, headers={"www-authenticate":
                                                'Bearer realm="https://auth.example.com/token",service="reg",scope="repository:library/nginx:pull"'})
        path = req.url.path
        if path.endswith("/manifests/1.27"):
            return httpx.Response(200, json=INDEX, headers={"content-type": INDEX["mediaType"], "docker-content-digest": "sha256:idx"})
        if path.endswith("/manifests/sha256:amd"):
            return httpx.Response(200, json=MANIFEST, headers={"content-type": MANIFEST["mediaType"]})
        if path.endswith("/blobs/sha256:cfg"):
            return httpx.Response(200, content=json.dumps(CFG).encode())
        return httpx.Response(404)

    monkeypatch.setattr(images.httpx, "Client", _registry(handler))
    r = images.RegistryInspector().inspect("nginx:1.27")
    st = {c["id"]: c["status"] for c in r["checks"]}
    assert st == {"image_format": "ok", "registry_reachable": "ok", "registry_auth": "ok", "tag_exists": "ok",
                  "platform_amd64": "ok"}
    assert r["platforms"] == ["linux/amd64", "linux/arm64"] and r["size"] == 150 and r["layers"] == 2
    assert r["digest"] == "sha256:idx" and r["config"]["exposedPorts"][1]["port"] == 8080
    assert any("registry-1.docker.io/v2/library/nginx" in u for u in calls)


def test_registry_inspector_errors(monkeypatch):
    def not_found(req):
        return httpx.Response(404)

    monkeypatch.setattr(images.httpx, "Client", _registry(not_found))
    st = {c["id"]: c["status"] for c in images.RegistryInspector().inspect("quay.io/x/y:1")["checks"]}
    assert st["tag_exists"] == "fail"

    def denied(req):
        return httpx.Response(401, headers={"www-authenticate": 'Basic realm="x"'})

    monkeypatch.setattr(images.httpx, "Client", _registry(denied))
    r = images.RegistryInspector().inspect("quay.io/x/y:1", username="u", password="p")
    auth = next(c for c in r["checks"] if c["id"] == "registry_auth")
    assert auth["status"] == "fail" and auth["params"]["credentialsProvided"]

    def boom(req):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(images.httpx, "Client", _registry(boom))
    r = images.RegistryInspector().inspect("quay.io/x/y")
    assert {c["id"]: c["status"] for c in r["checks"]}["registry_reachable"] == "fail"
    assert any(x["code"] == "latest_tag" for x in r["risks"])

    def slow(req):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(images.httpx, "Client", _registry(slow))
    r = images.RegistryInspector().inspect("quay.io/x/y:latest")
    assert "timeout" in next(c for c in r["checks"] if c["id"] == "registry_reachable")["params"]["error"]

    def server_error(req):
        return httpx.Response(500)

    monkeypatch.setattr(images.httpx, "Client", _registry(server_error))
    st = {c["id"]: c["status"] for c in images.RegistryInspector().inspect("quay.io/x/y:1")["checks"]}
    assert st["tag_exists"] == "unknown"
    assert images.RegistryInspector().inspect("Not Valid")["checks"] == [{"id": "image_format", "status": "fail"}]


def test_registry_inspector_single_arch_and_no_amd64(monkeypatch):
    def single(req):
        if req.url.path.endswith("/manifests/1"):
            return httpx.Response(200, json=MANIFEST, headers={"content-type": MANIFEST["mediaType"]})
        return httpx.Response(200, content=json.dumps({**CFG, "architecture": "arm64"}).encode())

    monkeypatch.setattr(images.httpx, "Client", _registry(single))
    r = images.RegistryInspector().inspect("ghcr.io/a/b:1")
    assert next(c for c in r["checks"] if c["id"] == "platform_amd64")["status"] == "fail"

    def arm_only(req):
        return httpx.Response(200, json={"manifests": [INDEX["manifests"][0]]},
                              headers={"content-type": "application/vnd.oci.image.index.v1+json"})

    monkeypatch.setattr(images.httpx, "Client", _registry(arm_only))
    r = images.RegistryInspector().inspect("ghcr.io/a/b:1")
    assert r["config"] is None and next(c for c in r["checks"] if c["id"] == "platform_amd64")["status"] == "fail"

    def bad_json(req):
        return httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})

    monkeypatch.setattr(images.httpx, "Client", _registry(bad_json))
    r = images.RegistryInspector().inspect("ghcr.io/a/b:1")
    assert next(c for c in r["checks"] if c["id"] == "manifest_readable")["status"] == "fail"


# ------------------------------------------------------------------ podman helpers
def _frame(stream: int, data: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + struct.pack(">I", len(data)) + data


def test_demux():
    raw = _frame(1, b"out line\n") + _frame(2, b"err line\n")
    assert _demux(raw) == "out line\nerr line\n"
    assert _demux(b"plain text log line that is long enough\n") == "plain text log line that is long enough\n"
    assert _demux(b"") == ""


def test_podman_summaries():
    c = container_summary({"Id": "abcdef1234567890", "Names": ["web"], "Image": "nginx", "State": "running",
                           "Ports": [{"host_port": 8080, "container_port": 80, "protocol": "tcp"}, {"container_port": 53}],
                           "Created": "2026-01-01"})
    assert c["id"] == "abcdef123456" and c["ports"] == ["0.0.0.0:8080->80/tcp", "53/tcp"]
    assert container_summary({"Id": "x" * 20})["name"] == "x" * 12
    i = image_summary({"Id": "sha256:" + "a" * 64, "RepoTags": None, "Size": 1})
    assert i["id"] == "a" * 12 and i["dangling"]


# ------------------------------------------------------------------ live helpers
@pytest.mark.parametrize("status,cls", [(401, K8sAuthFailed), (403, K8sForbidden), (404, K8sNotFound),
                                        (409, K8sConflict), (422, K8sInvalid), (400, K8sInvalid),
                                        (504, K8sTimeout), (500, K8sUnavailable), (429, K8sUnavailable)])
def test_map_api_error(status, cls):
    body = json.dumps({"message": "boom", "reason": "X", "details": {"causes": [{"field": "spec", "message": "bad"}]}})
    exc = map_api_error(status, body)
    assert isinstance(exc, cls) and exc.params["status"] == status and exc.details == "boom"
    assert exc.params["causes"] == [{"field": "spec", "message": "bad"}]


def test_map_api_error_non_json():
    exc = map_api_error(500, "<html>gateway</html>", "Bad Gateway")
    assert exc.details == "Bad Gateway"
    assert map_api_error(500, "[]").details == "[]"


def test_map_transport_exception():
    from kubernetes.config.config_exception import ConfigException

    assert isinstance(map_transport_exception(urllib3.exceptions.ReadTimeoutError(None, "/", "t")), K8sTimeout)
    mre = urllib3.exceptions.MaxRetryError(None, "/", urllib3.exceptions.ConnectTimeoutError("c"))
    e = map_transport_exception(mre)
    assert type(e) is K8sUnavailable and e.params["reason"] == "connect_timeout"
    mre = urllib3.exceptions.MaxRetryError(None, "/", urllib3.exceptions.ReadTimeoutError(None, "/", "r"))
    assert isinstance(map_transport_exception(mre), K8sTimeout)
    ssl_ = urllib3.exceptions.MaxRetryError(None, "/", urllib3.exceptions.SSLError("cert"))
    e = map_transport_exception(ssl_)
    assert isinstance(e, K8sUnavailable) and e.params["reason"] == "tls"
    assert isinstance(map_transport_exception(ConfigException("exec failed")), K8sAuthFailed)
    assert type(map_transport_exception(OSError("refused"))) is K8sUnavailable


def test_safe_server():
    assert _safe_server("https://user:pw@10.0.0.1:6443/path") == "https://10.0.0.1:6443"
    assert _safe_server(None) is None
    assert _safe_server("https://k8s.local") == "https://k8s.local"


class FakeResp:
    def __init__(self, chunks, error=None):
        self.chunks = chunks
        self.error = error
        self.closed = False

    def stream(self, *_a, **_k):
        yield from self.chunks
        if self.error:
            raise self.error

    def release_conn(self):
        pass

    def close(self):
        self.closed = True


def test_log_stream_dedup_and_reconnect():
    responses = [
        FakeResp([b"2026-01-01T00:00:01Z a\n2026-01-01T00:00:02Z b", b"\n"],
                 error=urllib3.exceptions.ReadTimeoutError(None, "/", "t")),
        # after reconnect with sinceTime the server repeats the last second
        FakeResp([b"2026-01-01T00:00:01Z a\n2026-01-01T00:00:02Z b\n2026-01-01T00:00:03Z c\n"]),
    ]
    opened = []

    def opener(tail_lines, since_time):
        opened.append((tail_lines, since_time))
        return responses.pop(0)

    s = _UrllibLogStream(opener, tail_lines=10, since_time=None)
    lines = list(s)
    assert lines == ["2026-01-01T00:00:01Z a", "2026-01-01T00:00:02Z b", "2026-01-01T00:00:03Z c"]
    assert opened == [(10, None), (None, "2026-01-01T00:00:02Z")]
    s.close()


def test_log_stream_first_open_error_propagates_and_close():
    def opener(**_):
        raise K8sNotFound("pod gone")

    with pytest.raises(K8sNotFound):
        list(_UrllibLogStream(opener, tail_lines=1, since_time=None))

    calls = []

    def opener2(tail_lines, since_time):
        calls.append(1)
        if len(calls) > 1:
            raise K8sNotFound("gone")
        return FakeResp([b"2026-01-01T00:00:01Z a\n"], error=OSError("reset"))

    assert list(_UrllibLogStream(opener2, tail_lines=1, since_time=None)) == ["2026-01-01T00:00:01Z a"]

    s = _UrllibLogStream(lambda **_: FakeResp([b"x\n"]), tail_lines=None, since_time=None)
    s.close()
    assert list(s) == []
