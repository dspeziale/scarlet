"""KubernetesService operations on the demo provider; manifest shape validation; sanitization; cache."""

from __future__ import annotations

import pytest

from pkm.config import KubernetesConfig
from pkm.errors import (
    BadRequest,
    K8sConflict,
    K8sForbidden,
    K8sInvalid,
    K8sNotFound,
    K8sUnsupported,
    NotFound,
    NotSupported,
    ValidationFailed,
)
from pkm.k8s.kinds import KINDS, get_kind, kind_for_manifest
from pkm.k8s.service import HIDDEN, KubernetesService, sanitize, validate_manifest_shape


@pytest.fixture
def svc(demo):
    s = KubernetesService(demo, KubernetesConfig(cache_ttl_seconds=60))
    yield s
    s.close()


def test_kinds_registry():
    d = get_kind("deployments")
    assert d.collection_path("ns") == "/apis/apps/v1/namespaces/ns/deployments"
    assert get_kind("nodes").item_path("n1", None) == "/api/v1/nodes/n1"
    assert get_kind("pods").collection_path(None) == "/api/v1/pods"
    assert d.public()["actions"] and d.group == "apps" and d.version == "v1"
    with pytest.raises(NotFound):
        get_kind("widgets")
    with pytest.raises(K8sUnsupported):
        kind_for_manifest("v1", "Widget")
    with pytest.raises(K8sUnsupported):
        kind_for_manifest("extensions/v1beta1", "Deployment")


def test_cache_and_invalidate(svc, demo, monkeypatch):
    calls = []
    orig = demo.list
    monkeypatch.setattr(demo, "list", lambda *a, **k: calls.append(1) or orig(*a, **k))
    svc.list_raw(KINDS["pods"], "production")
    svc.list_raw(KINDS["pods"], "production")
    assert len(calls) == 1
    svc.invalidate()
    svc.list_raw(KINDS["pods"], "production")
    assert len(calls) == 2


def test_list_unsupported_kind(svc, demo, monkeypatch):
    monkeypatch.setattr(demo, "list", lambda *a, **k: (_ for _ in ()).throw(K8sNotFound("nf")))
    with pytest.raises(K8sUnsupported) as e:
        svc.list_raw(KINDS["horizontalpodautoscalers"])
    assert e.value.params["minVersion"] == "1.23"


def test_snapshot_partial_on_forbidden(svc, demo, monkeypatch):
    orig = demo.list

    def guarded(kind, *a, **k):
        if kind.key == "secrets":
            raise K8sForbidden("no secrets")
        return orig(kind, *a, **k)

    monkeypatch.setattr(demo, "list", guarded)
    data, partial = svc.snapshot()
    assert data["secrets"] == [] and partial == [{"kind": "secrets", "code": "k8s_forbidden", "message": "no secrets"}]
    ov = svc.overview()
    assert ov["partial"] and ov["nodes"]["notReady"] == 1


def test_overview(svc):
    ov = svc.overview()
    assert ov["nodes"] == {"total": 3, "ready": 2, "notReady": 1, "cordoned": 0}
    assert ov["resources"]["metricsAvailable"] and ov["resources"]["usage"]["cpu"] > 0
    assert ov["storage"]["pvcPending"] == 1 and ov["issues"]["counts"]["CRITICAL"] >= 1
    assert ov["restarts"]["top"][0]["restarts"] >= ov["restarts"]["top"][-1]["restarts"]
    assert ov["events"]["warnings"] > 0


def test_detail_and_secret_masking(svc):
    d = svc.detail("secrets", "api-credentials", "production")
    assert set(d["object"]["data"].values()) == {HIDDEN}
    d = svc.detail("secrets", "api-credentials", "production", reveal=True)
    assert d["object"]["data"]["DB_USER"] == "c2hvcA=="
    obj = {"kind": "Secret", "metadata": {"name": "s", "managedFields": [1], "annotations": {
        "kubectl.kubernetes.io/last-applied-configuration": '{"data": {"p": "x"}}'}}, "stringData": {"p": "x"}}
    s = sanitize(obj)
    assert "managedFields" not in s["metadata"] and s["stringData"] == {"p": HIDDEN}
    assert "kubectl.kubernetes.io/last-applied-configuration" not in s["metadata"]["annotations"]
    assert sanitize(obj, managed_fields=True)["metadata"]["managedFields"] == [1]
    assert svc.detail("nodes", "node-01", "ignored")["summary"]["ready"]


def test_events_for(svc):
    pods = svc.list_summaries("pods", "production")["items"]
    crash = next(p for p in pods if p["status"] == "CrashLoopBackOff")
    ev = svc.events_for("pods", crash["name"], "production")
    assert ev and ev[0]["reason"] == "BackOff"
    assert svc.events_for("nodes", "node-03", None)[0]["reason"] == "NodeNotReady"
    assert svc.list_summaries("events")["items"][0]["lastTimestamp"]


def test_diagnose_resource(svc):
    assert any(i["reason"] == "WorkloadUnavailable" for i in svc.diagnose("deployments", "worker-prod", "production"))
    assert any(i["reason"] == "NodeNotReady" for i in svc.diagnose("nodes", "node-03", None))
    pod = next(p for p in svc.list_summaries("pods", "production")["items"] if p["status"] == "ImagePullBackOff")
    assert svc.diagnose("pods", pod["name"], "production")[0]["reason"] == "ImagePullBackOff"
    assert svc.diagnose("deployments", "web-prod", "production") == []


def test_scale_restart_pause(svc):
    assert svc.scale("deployments", "web-prod", "production", 5)["ready"] == "5/5"
    assert svc.scale("statefulsets", "redis", "production", 1)["replicas"] == 1
    with pytest.raises(NotSupported):
        svc.scale("daemonsets", "kube-proxy", "kube-system", 2)
    before = {p["name"] for p in svc.list_summaries("pods", "production")["items"] if p["name"].startswith("web-prod")}
    svc.restart("deployments", "web-prod", "production")
    after = {p["name"] for p in svc.list_summaries("pods", "production")["items"] if p["name"].startswith("web-prod")}
    assert before.isdisjoint(after) and len(after) == 5
    svc.restart("daemonsets", "kube-proxy", "kube-system")
    with pytest.raises(NotSupported):
        svc.restart("jobs", "x", "production")
    assert svc.set_paused("web-prod", "production", True)["health"] == "suspended"
    with pytest.raises(BadRequest) as e:
        svc.rollback("web-prod", "production", None)
    assert e.value.params["rule"] == "paused"
    assert svc.set_paused("web-prod", "production", False)["paused"] is False


def test_rollout_and_rollback(svc):
    info = svc.rollout("web-prod", "production")
    assert [h["revision"] for h in info["history"]] == [2, 1] and info["history"][0]["current"]
    assert "pod-template-hash" not in info["history"][1]["template"]["metadata"]["labels"]
    res = svc.rollback("web-prod", "production", None)
    assert res["revision"] == 1
    info = svc.rollout("web-prod", "production")
    current = next(h for h in info["history"] if h["current"])
    assert current["images"] == ["nginx:1.25.4"] and current["revision"] == 3
    with pytest.raises(ValidationFailed):
        svc.rollback("web-prod", "production", 99)
    with pytest.raises(BadRequest):
        svc.rollback("web-prod", "production", 3)
    with pytest.raises(BadRequest) as e:
        svc.rollback("api-prod", "production", None)
    assert e.value.params["rule"] == "no_history"


def test_cronjob_ops(svc):
    assert svc.set_cronjob_suspended("db-backup", "production", True)["suspend"] is True
    job = svc.trigger_cronjob("db-backup", "production")
    assert job["kind"] == "Job" and job["name"].startswith("db-backup-manual-")


def test_cordon_and_drain(svc):
    assert svc.set_cordon("node-02", True)["unschedulable"] is True
    assert svc.set_cordon("node-02", False)["unschedulable"] is False
    plan = svc.drain_plan("node-02")
    actions = {p["name"]: (p["action"], p["reason"]) for p in plan["pods"]}
    assert any(a == ("skip", "daemonset") for a in actions.values())
    assert any(a == ("evict", "finished") for a in actions.values())
    steps = []
    # web-prod has a PDB with minAvailable 2: evictions of those pods are retried until the timeout
    res = svc.drain("node-02", force_unmanaged=False, delete_emptydir=False, timeout_seconds=1,
                    progress=lambda s, d: steps.append(s), cancelled=lambda: False)
    assert steps[0] == "cordoned" and "evicted" in steps
    assert res["skipped"] and set(res["results"].values()) <= {"evicted", "gone", "blocked_by_pdb"}
    with pytest.raises(K8sNotFound):
        svc.drain_plan("nope")


def test_drain_blocked_by_unmanaged(svc, demo):
    demo.apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "lonely", "namespace": "default"},
                "spec": {"nodeName": "node-01", "containers": [{"name": "c", "image": "busybox"}],
                         "volumes": [{"name": "t", "emptyDir": {}}]}, "status": {"phase": "Running"}})
    plan = svc.drain_plan("node-01")
    assert ("blocked", "unmanaged") in {(p["action"], p["reason"]) for p in plan["pods"]}
    with pytest.raises(BadRequest) as e:
        svc.drain("node-01", force_unmanaged=False, delete_emptydir=False, timeout_seconds=5,
                  progress=lambda *a: None, cancelled=lambda: False)
    assert e.value.params["rule"] == "drain_blocked"
    res = svc.drain("node-01", force_unmanaged=True, delete_emptydir=True, timeout_seconds=5,
                    progress=lambda *a: None, cancelled=lambda: True)
    assert res["cancelled"]


def test_apply_create_delete(svc, demo):
    cm = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "c1", "namespace": "staging"}, "data": {"a": "1"}}
    assert svc.apply(dict(cm), dry_run=True)["metadata"]["uid"]
    with pytest.raises(K8sNotFound):
        svc.get_raw(KINDS["configmaps"], "c1", "staging")
    svc.apply(dict(cm), dry_run=False)
    assert svc.get_raw(KINDS["configmaps"], "c1", "staging")["data"] == {"a": "1"}
    with pytest.raises(K8sConflict):
        demo.create(dict(cm))
    with pytest.raises(K8sNotFound):
        svc.apply({**cm, "metadata": {"name": "c2", "namespace": "ghost"}}, dry_run=True)
    bad = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "d", "namespace": "staging"},
           "spec": {"selector": {"matchLabels": {"a": "b"}}, "template": {"metadata": {"labels": {"a": "c"}},
                                                                         "spec": {"containers": [{"name": "x"}]}}}}
    with pytest.raises(K8sInvalid) as e:
        svc.apply(bad, dry_run=True)
    assert e.value.params["causes"][0]["field"] == "spec.template.metadata.labels"
    bad["spec"]["template"]["metadata"]["labels"] = {"a": "b"}
    bad["spec"]["template"]["spec"]["containers"] = []
    with pytest.raises(K8sInvalid):
        svc.apply(bad, dry_run=True)
    svc.delete("configmaps", "c1", "staging")
    with pytest.raises(K8sNotFound):
        svc.delete("configmaps", "c1", "staging")
    # cascade: deleting a deployment removes its replicasets and pods
    svc.delete("deployments", "web-prod", "production")
    assert not [p for p in svc.list_raw(KINDS["pods"], "production") if p["metadata"]["name"].startswith("web-prod")]
    svc.delete("namespaces", "staging", None)
    assert svc.list_raw(KINDS["pods"], "staging") == []
    # generateName and job/service/namespace creation side effects
    job = demo.create({"apiVersion": "batch/v1", "kind": "Job", "metadata": {"generateName": "j-", "namespace": "default"},
                       "spec": {}})
    assert job["metadata"]["name"].startswith("j-") and job["status"]["active"] == 1
    demo.apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "newns"}})
    assert demo.get(KINDS["namespaces"], "newns")["status"]["phase"] == "Active"


def test_pod_delete_recreates_owned(svc):
    pod = next(p for p in svc.list_raw(KINDS["pods"], "production") if p["metadata"]["name"].startswith("web-prod"))
    svc.delete("pods", pod["metadata"]["name"], "production")
    names = [p["metadata"]["name"] for p in svc.list_raw(KINDS["pods"], "production") if p["metadata"]["name"].startswith("web-prod")]
    assert pod["metadata"]["name"] not in names and len(names) == 3


def test_demo_logs_and_patch(demo):
    pods = demo.list(KINDS["pods"], "production")
    crash = next(p for p in pods if "api-prod" in p["metadata"]["name"]
                 and p["status"]["containerStatuses"][0].get("state", {}).get("waiting"))
    text = demo.pod_logs(crash["metadata"]["name"], "production", tail_lines=2, timestamps=False, limit_bytes=1000)
    assert text.count("\n") == 2 and "[DEMO]" in text
    assert demo.pod_logs(crash["metadata"]["name"], "production", tail_lines=0) == ""
    stream = demo.stream_pod_logs(crash["metadata"]["name"], "production", tail_lines=3)
    assert len(list(stream)) == 3  # crashing container: no follow
    web = next(p for p in pods if p["metadata"]["name"].startswith("web-prod"))
    s = demo.stream_pod_logs(web["metadata"]["name"], "production", tail_lines=1)
    it = iter(s)
    first = next(it)
    s.close()
    assert first.split(" ", 1)[0].endswith("Z")
    with pytest.raises(K8sNotFound):
        demo.patch(KINDS["pods"], "nope", "production", {})
    with pytest.raises(K8sInvalid):
        demo.patch(KINDS["deployments"], "web-prod", "production", [{"op": "move", "path": "/a"}], patch_type="json")
    dry = demo.patch(KINDS["deployments"], "web-prod", "production", {"spec": {"replicas": 9}}, dry_run=True)
    assert dry["spec"]["replicas"] == 9
    assert demo.get(KINDS["deployments"], "web-prod", "production")["spec"]["replicas"] == 3
    demo.patch(KINDS["deployments"], "web-prod", "production", [{"op": "remove", "path": "/metadata/labels"}],
               patch_type="json")
    assert demo.list(KINDS["pods"], label_selector="app=web-prod")
    assert demo.list(KINDS["pods"], field_selector="spec.nodeName=node-03")
    with pytest.raises(K8sConflict):
        _evict_until_pdb(demo)


def _evict_until_pdb(demo):
    pdb = demo.get(KINDS["poddisruptionbudgets"], "web-prod", "production")
    pdb["status"]["disruptionsAllowed"] = 0
    demo._put(pdb)
    pod = next(p for p in demo.list(KINDS["pods"], "production") if p["metadata"]["labels"].get("app") == "web-prod")
    demo.evict(pod["metadata"]["name"], "production")


@pytest.mark.parametrize("doc,field", [
    ("text", None), ({"kind": "ConfigMap", "metadata": {"name": "a"}}, "apiVersion"),
    ({"apiVersion": "v1", "metadata": {"name": "a"}}, "kind"), ({"apiVersion": "v1", "kind": "ConfigMap"}, "metadata"),
    ({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {}}, "metadata.name"),
    ({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "Bad_Name"}}, "metadata.name"),
    ({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "a", "namespace": "B!"}}, "metadata.namespace"),
    ({"apiVersion": "v1", "kind": "Node", "metadata": {"name": "a", "namespace": "x"}}, "metadata.namespace"),
])
def test_validate_manifest_shape_errors(doc, field):
    with pytest.raises(ValidationFailed) as e:
        validate_manifest_shape(doc, 0)
    if field:
        assert e.value.params.get("field") == field


def test_validate_manifest_shape_strips_server_fields():
    doc = {"apiVersion": "v1", "kind": "ConfigMap", "status": {}, "metadata": {
        "name": "a", "uid": "u", "resourceVersion": "1", "managedFields": [], "creationTimestamp": "x", "generation": 1}}
    out = validate_manifest_shape(doc, 0)
    assert out["metadata"] == {"name": "a"} and "status" not in out
