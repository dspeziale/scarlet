"""Integration tests against a real Kubernetes cluster and a real Podman API.

  PKM_IT_KUBECONFIG=/path/kubeconfig   pytest -m integration_k8s
  PKM_IT_PODMAN_URL=http://host:port   pytest -m integration_podman
"""

from __future__ import annotations

import os
import threading
import time
import uuid

import httpx
import pytest

from pkm.config import KubernetesConfig, PodmanConfig
from pkm.errors import K8sNotFound
from pkm.k8s import manifests
from pkm.k8s.kinds import KINDS
from pkm.k8s.live import LiveKubernetes
from pkm.k8s.service import KubernetesService
from pkm.podman.client import LivePodman

KUBECONFIG = os.environ.get("PKM_IT_KUBECONFIG")
PODMAN_URL = os.environ.get("PKM_IT_PODMAN_URL")
IMAGE = os.environ.get("PKM_IT_IMAGE", "docker.io/library/nginx")
TAG = os.environ.get("PKM_IT_TAG", "1.27-alpine")


def wait(fn, timeout=240, interval=2, what="condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timeout waiting for {what}; last={last!r}")


# ------------------------------------------------------------------ Kubernetes
@pytest.fixture(scope="module")
def k8s():
    if not KUBECONFIG:
        pytest.skip("PKM_IT_KUBECONFIG not set")
    cfg = KubernetesConfig(kubeconfig=KUBECONFIG, request_timeout=30, cache_ttl_seconds=0)
    svc = KubernetesService(LiveKubernetes(cfg), cfg)
    yield svc
    svc.close()


@pytest.fixture(scope="module")
def ns(k8s):
    name = f"pkm-it-{uuid.uuid4().hex[:6]}"
    k8s.apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": name}}, dry_run=False)
    yield name
    k8s.delete("namespaces", name, None)


def _ready(k8s, ns, name, replicas):
    s = k8s.detail("deployments", name, ns)["summary"]
    return s if s["readyReplicas"] == replicas and s["updatedReplicas"] == replicas and s["health"] == "healthy" else None


@pytest.mark.integration_k8s
def test_k8s_info_and_reads(k8s):
    info = k8s.info()
    assert info["connected"] and info["version"]["gitVersion"].startswith("v1.")
    nodes = k8s.list_summaries("nodes")["items"]
    assert nodes and all(n["ready"] for n in nodes)
    assert {n["name"] for n in k8s.list_summaries("namespaces")["items"]} >= {"default", "kube-system"}
    assert k8s.list_summaries("pods", "kube-system")["count"] > 0
    assert k8s.list_summaries("deployments", "kube-system")["count"] > 0
    assert k8s.list_summaries("services")["count"] > 0
    k8s.list_summaries("events")
    for key in KINDS:
        k8s.list_summaries(key)  # every managed kind is served by a current cluster
    ov = k8s.overview()
    assert ov["nodes"]["ready"] == len(nodes) and ov["partial"] == []
    k8s.node_metrics()  # metrics-server is optional: None or a list


@pytest.mark.integration_k8s
def test_k8s_deploy_lifecycle(k8s, ns):
    spec = manifests.DeploySpec(name="web", namespace=ns, image=IMAGE, tag=TAG, port=80, replicas=1,
                                readiness={"type": "http", "path": "/"}, liveness={"type": "tcp"},
                                networking={"service_type": "ClusterIP"})
    docs = manifests.generate(spec)
    for d in docs:
        assert k8s.apply(d, dry_run=True)["metadata"]["name"]  # server-side dry run
    for d in docs:
        k8s.apply(d, dry_run=False)
    wait(lambda: _ready(k8s, ns, "web", 1), what="deployment ready")
    # scale
    k8s.scale("deployments", "web", ns, 2)
    wait(lambda: _ready(k8s, ns, "web", 2), what="2 replicas")
    # logs + stream
    pods = [p for p in k8s.list_summaries("pods", ns)["items"] if p["health"] == "healthy"]
    pod = pods[0]["name"]
    text = wait(lambda: k8s.pod_logs(pod, ns, tail_lines=20, timestamps=True), what="logs")
    assert all(line.split(" ", 1)[0].endswith("Z") for line in text.splitlines())
    stream = k8s.stream_pod_logs(pod, ns, tail_lines=3)
    got: list[str] = []

    def reader():
        for line in stream:
            got.append(line)
            if len(got) >= 1:
                break

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(30)
    stream.close()
    assert got and got[0].split(" ", 1)[0].endswith("Z")
    # restart -> new revision, rollout history and rollback
    k8s.restart("deployments", "web", ns)
    wait(lambda: len(k8s.rollout("web", ns)["history"]) >= 2, what="second revision")
    wait(lambda: _ready(k8s, ns, "web", 2), what="restart complete")
    hist = k8s.rollout("web", ns)["history"]
    assert hist[0]["current"] and hist[0]["revision"] == 2
    res = k8s.rollback("web", ns, None)
    assert res["revision"] == 1
    wait(lambda: next(h for h in k8s.rollout("web", ns)["history"] if h["current"])["revision"] == 3, what="rollback")
    # pause / resume
    assert k8s.set_paused("web", ns, True)["paused"]
    assert k8s.set_paused("web", ns, False)["paused"] is False
    # events, relations, diagnose healthy
    assert wait(lambda: k8s.events_for("deployments", "web", ns), what="events")
    rel = k8s.relations("deployments", "web", ns)
    assert {"ReplicaSet", "Pod", "Service", "Node"} <= {n["kind"] for n in rel["nodes"]}
    assert k8s.diagnose("deployments", "web", ns) == []
    # delete a current pod: the ReplicaSet recreates it
    pod = next(p["name"] for p in k8s.list_summaries("pods", ns)["items"] if p["name"].startswith("web-"))
    k8s.delete("pods", pod, ns)
    wait(lambda: _ready(k8s, ns, "web", 2), what="pod recreated")

    def gone():
        try:
            k8s.get_raw(KINDS["pods"], pod, ns)  # still terminating during the grace period
            return False
        except K8sNotFound:
            return True

    wait(gone, timeout=90, what="deleted pod gone")


@pytest.mark.integration_k8s
def test_k8s_diagnose_imagepull(k8s, ns):
    spec = manifests.DeploySpec(name="broken", namespace=ns, image=IMAGE, tag="does-not-exist-pkm", port=80,
                                networking={"service_type": "none"})
    for d in manifests.generate(spec):
        k8s.apply(d, dry_run=False)

    def found():
        issues = k8s.diagnose("deployments", "broken", ns)
        return next((i for i in issues if i["reason"] == "ImagePullBackOff" and i["likely_cause"]), None)

    issue = wait(found, timeout=240, what="ImagePullBackOff issue")
    assert issue["likely_cause"] == "tag_exists" and issue["guide"] == "imagepullbackoff"
    assert any(i["reason"] == "WorkloadUnavailable" and i["severity"] == "CRITICAL"
               for i in k8s.diagnose("deployments", "broken", ns))
    k8s.delete("deployments", "broken", ns)


@pytest.mark.integration_k8s
def test_k8s_cordon_and_drain_plan(k8s):
    node = k8s.list_summaries("nodes")["items"][0]["name"]
    try:
        assert k8s.set_cordon(node, True)["unschedulable"]
    finally:
        assert k8s.set_cordon(node, False)["unschedulable"] is False
    plan = k8s.drain_plan(node)
    assert plan["pods"] and any(p["reason"] == "daemonset" for p in plan["pods"])


@pytest.mark.integration_k8s
def test_k8s_secret_masking_and_cronjob(k8s, ns):
    k8s.apply({"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "s", "namespace": ns},
               "stringData": {"password": "p"}}, dry_run=False)
    assert k8s.detail("secrets", "s", ns)["object"]["data"] == {"password": "<hidden>"}
    k8s.apply({"apiVersion": "batch/v1", "kind": "CronJob", "metadata": {"name": "cj", "namespace": ns},
               "spec": {"schedule": "0 0 1 1 *", "jobTemplate": {"spec": {"template": {"spec": {
                   "restartPolicy": "Never", "containers": [{"name": "c", "image": f"{IMAGE}:{TAG}",
                                                             "command": ["true"]}]}}}}}}, dry_run=False)
    assert k8s.set_cronjob_suspended("cj", ns, True)["suspend"]
    job = k8s.trigger_cronjob("cj", ns)
    assert job["name"].startswith("cj-manual-")


# ------------------------------------------------------------------ Podman
@pytest.fixture(scope="module")
def podman():
    if not PODMAN_URL:
        pytest.skip("PKM_IT_PODMAN_URL not set")
    p = LivePodman(PodmanConfig(url=PODMAN_URL, timeout=60))
    yield p
    p.close()


@pytest.mark.integration_podman
def test_podman_lifecycle(podman):
    info = podman.info()
    assert info["connected"] and info["version"] and info["apiVersion"]
    ref = os.environ.get("PKM_IT_PODMAN_IMAGE", "docker.io/library/busybox:1.36")
    pulled = podman.pull_image(ref)
    assert pulled["id"]
    name = f"pkm-it-{uuid.uuid4().hex[:6]}"
    api = f"{PODMAN_URL.rstrip('/')}/v4.0.0/libpod"
    r = httpx.post(f"{api}/containers/create", json={"image": ref, "name": name,
                                                     "command": ["sh", "-c", "echo hello-pkm; sleep 300"]}, timeout=60)
    assert r.status_code == 201, r.text
    try:
        podman.container_action(name, "start")
        assert any(c["name"] == name and c["state"] == "running" for c in podman.list_containers())
        assert podman.inspect_container(name)["Name"].lstrip("/") == name
        lines = wait(lambda: podman.container_logs(name, tail=10, timestamps=False), timeout=30, interval=1, what="logs")
        assert "hello-pkm" in lines
        assert podman.container_logs(name, tail=10, timestamps=True)[0].split(" ")[0][:4].isdigit()
        stats = podman.stats()
        # Nested Podman (cgroupfs inside a container) reports no stats at all; on a host every running
        # container is listed.
        assert isinstance(stats, list) and (not stats or any(s["name"] == name for s in stats))
        podman.container_action(name, "stop")
        assert next(c for c in podman.list_containers() if c["name"] == name)["state"] in ("exited", "stopped")
        podman.container_action(name, "restart")
    finally:
        podman.remove_container(name, force=True)
    assert all(c["name"] != name for c in podman.list_containers())
    images = podman.list_images()
    img = next(i for i in images if any(ref.split("/")[-1] in t for t in i["tags"]))
    assert podman.inspect_image(img["fullId"])["Id"]
    podman.remove_image(img["fullId"], force=True)
    assert all(i["fullId"] != img["fullId"] for i in podman.list_images())


@pytest.mark.integration_k8s
def test_api_live_against_cluster(tmp_path):
    if not KUBECONFIG:
        pytest.skip("PKM_IT_KUBECONFIG not set")
    from fastapi.testclient import TestClient

    from pkm.main import create_app

    from .conftest import API, complete_setup, login, make_settings

    s = make_settings(tmp_path, mode="live", environment="production",
                      kubernetes={"kubeconfig": KUBECONFIG, "request_timeout": 30},
                      podman={"url": PODMAN_URL or "http://127.0.0.1:1", "enabled": bool(PODMAN_URL)})
    app = create_app(s, start_background=False)
    with TestClient(app) as anon:
        complete_setup(anon, app.state.ctx)
        c = login(app, "admin")
        st = c.get(f"{API}/system/status").json()
        assert st["mode"] == "live" and st["kubernetes"]["connected"]
        ov = c.get(f"{API}/cluster/overview").json()
        assert ov["partial"] == [] and ov["nodes"]["ready"] >= 1 and ov["pods"]["total"] > 0
        assert c.get(f"{API}/cluster/issues").status_code == 200
        ha = c.get(f"{API}/cluster/ha", params={"namespace": "kube-system"}).json()
        assert any(w["name"] == "coredns" for w in ha["workloads"])
        rel = c.get(f"{API}/k8s/deployments/kube-system/coredns/relations").json()
        assert {"ReplicaSet", "Pod", "Service"} <= {n["kind"] for n in rel["nodes"]}
        d = c.get(f"{API}/k8s/deployments/kube-system/coredns").json()
        assert "kind: Deployment" in d["yaml"] and d["summary"]["health"] == "healthy"
        assert c.get(f"{API}/search", params={"q": "coredns"}).json()["total"] >= 1
        assert c.get(f"{API}/monitoring/nodes").json()["nodes"]
        h = {x["id"]: x for x in c.get(f"{API}/health").json()["checks"]}
        assert h["kubernetes"]["status"] == "healthy"
        r = c.post(f"{API}/k8s/validate", json={"yaml": "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: it\n"}).json()
        assert r["valid"] and r["serverChecked"]
        app.state.ctx.monitor_once()
        assert app.state.ctx.last_monitor["error"] is None
