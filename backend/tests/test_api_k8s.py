"""Kubernetes endpoints in DEMO mode."""

from __future__ import annotations

import json
import time

from .conftest import API, pod_name

WEB = f"{API}/k8s/deployments/production/web-prod"


def wait_op(client, op_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        op = client.get(f"{API}/operations/{op_id}").json()
        if op["status"] != "running":
            return op
        time.sleep(0.2)
    raise AssertionError("operation did not finish")


def test_kinds_and_lists(admin):
    kinds = admin.get(f"{API}/k8s/kinds").json()["items"]
    assert {k["key"] for k in kinds} >= {"pods", "deployments", "nodes", "secrets", "ingresses"}
    for k in kinds:
        r = admin.get(f"{API}/k8s/{k['key']}")
        assert r.status_code == 200, k["key"]
        assert r.json()["kind"]["kind"] == k["kind"]
    r = admin.get(f"{API}/k8s/pods", params={"namespace": "production", "labelSelector": "app=web-prod"}).json()
    assert r["count"] == 3 and all(p["namespace"] == "production" for p in r["items"])
    assert admin.get(f"{API}/k8s/pods", params={"namespace": "Bad_NS"}).status_code == 422


def test_detail_yaml_events_relations_diagnose_metrics(admin):
    d = admin.get(WEB).json()
    assert d["summary"]["ready"] == "3/3" and "kind: Deployment" in d["yaml"] and "managedFields" not in d["yaml"]
    assert admin.get(f"{API}/k8s/nodes/_/node-01").json()["summary"]["ready"]
    assert admin.get(f"{API}/k8s/deployments/production/ghost").json()["error"]["code"] == "k8s_not_found"
    assert admin.get(f"{API}/k8s/deployments/production/Bad_Name").status_code == 422
    assert admin.get(f"{WEB}/events").json()["items"][0]["reason"] == "ScalingReplicaSet"
    rel = admin.get(f"{WEB}/relations").json()
    assert {n["kind"] for n in rel["nodes"]} >= {"Deployment", "ReplicaSet", "Pod", "Service"}
    diag = admin.get(f"{API}/k8s/deployments/production/worker-prod/diagnose").json()["items"]
    assert {i["reason"] for i in diag} == {"WorkloadUnavailable", "ImagePullBackOff"}
    m = admin.get(f"{WEB}/metrics").json()
    assert m["available"] and len(m["containers"]) == 3 and m["containers"][0]["memoryLimit"]
    p = pod_name(admin, "production", "web-prod")
    assert len(admin.get(f"{API}/k8s/pods/production/{p}/metrics").json()["containers"]) == 1
    node = admin.get(f"{API}/k8s/nodes/_/node-01/metrics").json()
    assert node["node"]["cpu"] > 0
    assert admin.get(f"{API}/k8s/nodes/_/node-03/metrics").json()["node"] is None


def test_secret_reveal_audited(admin, ctx):
    s = admin.get(f"{API}/k8s/secrets/production/api-credentials").json()
    assert s["object"]["data"]["DB_PASSWORD"] == "<hidden>" and "<hidden>" in s["yaml"]
    s = admin.get(f"{API}/k8s/secrets/production/api-credentials?reveal=true").json()
    assert s["object"]["data"]["DB_PASSWORD"] != "<hidden>"
    assert ctx.audit.search(action="secret.reveal")["total"] == 1
    assert admin.get(f"{API}/k8s/configmaps/production/web-config?reveal=true").status_code == 400


def test_logs(admin, ctx):
    p = pod_name(admin, "production", "web-prod")
    r = admin.get(f"{API}/k8s/pods/production/{p}/logs", params={"tail": 5}).json()
    assert r["count"] == 5 and r["container"] == "web" and r["truncated"]
    r = admin.get(f"{API}/k8s/pods/production/{p}/logs", params={"tail": 5, "timestamps": False}).json()
    assert r["lines"][0].startswith("[DEMO]")
    r = admin.get(f"{API}/k8s/pods/production/{p}/logs", params={"tail": 3, "download": True})
    assert "attachment" in r.headers["content-disposition"] and r.text.count("\n") == 3
    assert ctx.audit.search(action="logs.download")["total"] == 1
    r = admin.get(f"{API}/k8s/pods/production/{p}/logs", params={"container": "nope"})
    assert r.status_code == 422 and r.json()["error"]["params"]["available"] == ["web"]
    assert admin.get(f"{API}/k8s/pods/production/{p}/logs", params={"tail": 0}).status_code == 422


def _sse_events(response, max_events):
    events, current = [], {}
    for line in response.iter_lines():
        if line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current["data"] = json.loads(line.split(":", 1)[1])
        elif line == "" and current:
            events.append(current)
            current = {}
            if len(events) >= max_events or events[-1].get("event") in ("end", "limit", "error"):
                break
    return events


def test_log_stream_ends_for_crashing_pod(admin, ctx):
    p = pod_name(admin, "production", "api-prod")
    crash = next(x for x in admin.get(f"{API}/k8s/pods", params={"namespace": "production"}).json()["items"]
                 if x["status"] == "CrashLoopBackOff")["name"]
    assert p
    with admin.stream("GET", f"{API}/k8s/pods/production/{crash}/logs/stream", params={"tail": 3}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _sse_events(r, 10)
    assert events[0]["event"] == "open" and events[0]["data"] == {"container": "api"}
    lines = [ln for e in events if "event" not in e for ln in e["data"]]
    assert len(lines) == 3 and events[-1]["event"] == "end"
    assert not ctx.log_streams.locked()


def test_log_stream_follow_then_disconnect(admin, ctx):
    p = pod_name(admin, "production", "web-prod")
    with admin.stream("GET", f"{API}/k8s/pods/production/{p}/logs/stream", params={"tail": 2}) as r:
        events = _sse_events(r, 3)
    assert events[0]["event"] == "open"
    assert sum(len(e["data"]) for e in events[1:]) >= 2


def test_log_stream_limit(admin, ctx):
    ctx.settings.logs.stream_max_lines = 100
    p = pod_name(admin, "production", "web-prod")
    with admin.stream("GET", f"{API}/k8s/pods/production/{p}/logs/stream", params={"tail": 150}) as r:
        events = _sse_events(r, 1000)
    assert events[-1]["event"] == "limit" and events[-1]["data"]["reason"] == "lines"


def test_scale_restart_rollout(admin, ctx):
    r = admin.post(f"{WEB}/scale", json={"replicas": 0})
    assert r.status_code == 428 and r.json()["error"]["params"]["expected"] == "web-prod"
    assert admin.post(f"{WEB}/scale", json={"replicas": 0, "confirm": "web-prod"}).json()["summary"]["health"] == "suspended"
    assert admin.post(f"{WEB}/scale", json={"replicas": 2}).json()["summary"]["ready"] == "2/2"
    assert admin.post(f"{API}/k8s/daemonsets/kube-system/kube-proxy/scale", json={"replicas": 2}).status_code == 501
    assert admin.post(f"{WEB}/restart").status_code == 200
    assert admin.post(f"{WEB}/pause").json()["summary"]["paused"]
    assert admin.post(f"{WEB}/resume").json()["summary"]["paused"] is False
    ro = admin.get(f"{WEB}/rollout").json()
    assert ro["history"][0]["current"] and "templateYaml" in ro["history"][0]
    assert admin.post(f"{WEB}/rollback", json={"revision": 999}).status_code == 422
    rb = admin.post(f"{WEB}/rollback", json={}).json()
    assert rb["revision"] == 2  # the restart created revision 3; "previous" is 2
    r = admin.post(f"{API}/k8s/deployments/production/api-prod/rollback", json={})
    assert r.status_code == 400 and r.json()["error"]["params"]["rule"] == "no_history"
    audit = {e["action"] for e in ctx.audit.search(limit=100)["items"]}
    assert {"workload.scale", "workload.restart", "rollout.pause", "rollout.resume", "rollout.rollback"} <= audit
    assert ctx.audit.search(action="rollout.rollback", result="failure")["total"] == 2


def test_restart_pod_and_unmanaged(admin, ctx):
    p = pod_name(admin, "production", "web-prod")
    assert admin.post(f"{API}/k8s/pods/production/{p}/restart").json() == {"deleted": p}
    ctx.k8s.provider.apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "lonely", "namespace": "default"},
                            "spec": {"containers": [{"name": "c", "image": "busybox"}]}, "status": {"phase": "Running"}})
    r = admin.post(f"{API}/k8s/pods/default/lonely/restart", json={})
    assert r.status_code == 428 and r.json()["error"]["params"]["reason"] == "unmanaged"
    assert admin.post(f"{API}/k8s/pods/default/lonely/restart", json={"confirm": "lonely"}).status_code == 200
    r = admin.post(f"{API}/k8s/pods/default/lonely/restart", json={"confirm": "lonely"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "k8s_not_found"


def test_cronjob_ops(admin):
    base = f"{API}/k8s/cronjobs/production/db-backup"
    assert admin.post(f"{base}/suspend", json={"suspend": True}).json()["summary"]["suspend"]
    assert admin.post(f"{base}/trigger").json()["summary"]["kind"] == "Job"


def test_nodes_and_drain(admin, ctx):
    assert admin.post(f"{API}/k8s/nodes/_/node-02/cordon").json()["summary"]["unschedulable"]
    assert admin.post(f"{API}/k8s/nodes/_/node-02/uncordon").json()["summary"]["unschedulable"] is False
    plan = admin.get(f"{API}/k8s/nodes/_/node-02/drain-plan").json()
    assert plan["node"] == "node-02" and plan["pods"]
    r = admin.post(f"{API}/k8s/nodes/_/node-02/drain", json={})
    assert r.status_code == 428
    r = admin.post(f"{API}/k8s/nodes/_/node-02/drain", json={"confirm": "node-02", "timeout_seconds": 30}).json()
    op = wait_op(admin, r["operation"]["id"])
    assert op["status"] == "succeeded" and op["steps"][0]["step"] == "cordoned"
    assert admin.get(f"{API}/operations").json()["items"][0]["id"] == op["id"]
    assert ctx.audit.search(action="node.drain.finish", result="success")["total"] == 1
    ctx.k8s.provider.apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "solo", "namespace": "default"},
                            "spec": {"nodeName": "node-01", "containers": [{"name": "c", "image": "b"}]},
                            "status": {"phase": "Running"}})
    r = admin.post(f"{API}/k8s/nodes/_/node-01/drain", json={"confirm": "node-01", "timeout_seconds": 30})
    assert r.status_code == 400 and r.json()["error"]["params"]["rule"] == "drain_blocked"
    assert admin.get(f"{API}/operations/nope").status_code == 404


def test_operation_cancel(admin, operator, ctx):
    import threading

    gate = threading.Event()
    op = ctx.operations.start("drain", "x", "admin", lambda o: gate.wait(5))
    r = operator.post(f"{API}/operations/{op.id}/cancel")
    assert r.status_code == 403
    assert admin.post(f"{API}/operations/{op.id}/cancel").status_code == 200
    gate.set()


def test_delete_with_confirmation(admin, ctx):
    r = admin.delete(f"{API}/k8s/configmaps/production/web-config")
    assert r.status_code == 428 and r.json()["error"]["params"]["risk"] == "medium"
    r = admin.delete(f"{API}/k8s/persistentvolumeclaims/staging/uploads-staging?confirm=wrong")
    assert r.status_code == 428 and r.json()["error"]["params"]["risk"] == "high"
    assert admin.delete(f"{API}/k8s/configmaps/production/web-config?confirm=web-config").json() == {"ok": True}
    assert admin.delete(f"{API}/k8s/storageclasses/_/standard?confirm=standard").status_code == 501
    r = admin.delete(f"{API}/k8s/configmaps/production/web-config?confirm=web-config")
    assert r.status_code == 404
    assert ctx.audit.search(action="resource.delete", result="failure")["total"] == 1
    p = pod_name(admin, "production", "web-prod")
    assert admin.delete(f"{API}/k8s/pods/production/{p}").status_code == 200  # managed pod: no confirmation


def test_validate_yaml(admin, viewer):
    r = admin.post(f"{API}/k8s/validate", json={"yaml": "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: [x\n"}).json()
    assert not r["valid"] and r["errors"][0]["line"] in (4, 5) and r["errors"][0]["column"]
    r = admin.post(f"{API}/k8s/validate", json={"yaml": "apiVersion: v1\nkind: Widget\nmetadata:\n  name: a\n"}).json()
    assert not r["valid"] and r["errors"][0]["code"] == "k8s_unsupported"
    r = admin.post(f"{API}/k8s/validate", json={"yaml": "# only a comment\n"}).json()
    assert not r["valid"]
    bad_dep = ("apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: d\n  namespace: staging\nspec:\n"
               "  selector:\n    matchLabels: {a: b}\n  template:\n    metadata:\n      labels: {a: c}\n"
               "    spec:\n      containers: [{name: x, image: nginx}]\n")
    r = admin.post(f"{API}/k8s/validate", json={"yaml": bad_dep}).json()
    assert r["serverChecked"] and not r["valid"] and r["errors"][0]["causes"]
    good = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: ok\n"
    r = admin.post(f"{API}/k8s/validate", json={"yaml": good, "namespace": "staging"}).json()
    assert r["valid"] and r["documents"][0]["namespace"] == "staging" and not r["documents"][0]["existed"]
    r = viewer.post(f"{API}/k8s/validate", json={"yaml": good}).json()
    assert r["valid"] and r["serverChecked"] is False


def test_apply_yaml(admin, operator, ctx):
    doc = "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: applied\n  namespace: staging\ndata:\n  k: v\n"
    r = admin.post(f"{API}/k8s/apply", json={"yaml": doc, "dry_run": True}).json()
    assert r["ok"] and r["dryRun"]
    assert ctx.audit.search(action="resource.apply")["total"] == 0
    r = admin.post(f"{API}/k8s/apply", json={"yaml": doc + "---\n" + doc.replace("applied", "applied2")}).json()
    assert r["ok"] and [x["existed"] for x in r["results"]] == [False, False] and "kind: ConfigMap" in r["results"][0]["result"]
    r = admin.post(f"{API}/k8s/apply", json={"yaml": doc}).json()
    assert r["results"][0]["existed"]
    assert ctx.audit.search(action="resource.apply")["total"] == 3
    r = admin.post(f"{API}/k8s/apply", json={"yaml": doc.replace("staging", "ghost")}).json()
    assert not r["ok"] and r["results"][0]["error"]["code"] == "k8s_not_found"
    assert admin.post(f"{API}/k8s/apply", json={"yaml": doc, "namespace": "Bad!"}).status_code == 422
    r = operator.post(f"{API}/k8s/apply", json={"yaml": doc, "force": True})
    assert r.status_code == 403
    many = "---\n".join([doc.replace("applied", f"c{i}") for i in range(51)])
    r = admin.post(f"{API}/k8s/apply", json={"yaml": many})
    assert r.status_code == 422 and "too many" in r.json()["error"]["message"]


def test_deploy_wizard(admin, operator, ctx):
    spec = {"name": "shop-ui", "namespace": "staging", "image": "nginx", "tag": "1.27", "port": 80, "replicas": 2,
            "readiness": {"type": "http"}, "liveness": {"type": "http"}}
    pv = admin.post(f"{API}/deploy/preview", json=spec).json()
    assert pv["valid"] and pv["risks"] == [] and pv["yaml"].count("kind:") == 2 and pv["blocking"] == []
    assert all(r["ok"] for r in pv["dryRun"])
    d = admin.post(f"{API}/deploy", json=spec).json()
    assert d["ok"] and {r["kind"] for r in d["results"]} == {"Deployment", "Service"}
    assert admin.get(f"{API}/k8s/deployments/staging/shop-ui").json()["summary"]["ready"] == "2/2"
    pv = admin.post(f"{API}/deploy/preview", json=spec).json()
    assert any(r["code"] == "overwrite_existing" for r in pv["risks"])
    pv = admin.post(f"{API}/deploy/preview", json={**spec, "namespace": "nowhere"}).json()
    assert pv["blocking"][0]["code"] == "namespace_missing" and not pv["valid"]
    pv = operator.post(f"{API}/deploy/preview", json={**spec, "namespace": "brand-new", "create_namespace": True}).json()
    assert pv["blocking"][0]["code"] == "namespace_create_forbidden"
    r = operator.post(f"{API}/deploy", json={**spec, "namespace": "brand-new", "create_namespace": True})
    assert r.status_code == 403
    d = admin.post(f"{API}/deploy", json={**spec, "name": "fresh", "namespace": "brand-new", "create_namespace": True}).json()
    assert d["ok"] and d["results"][0]["kind"] == "Namespace"
    assert admin.post(f"{API}/deploy/preview", json={**spec, "name": "Bad"}).status_code == 422
    assert ctx.audit.search(action="deploy.wizard")["total"] == 2


def test_image_inspect(operator, ctx):
    r = operator.post(f"{API}/images/inspect", json={"image": "nginx:1.27"}).json()
    assert r["demo"] and r["config"]["exposedPorts"][0]["port"] == 80
    r = operator.post(f"{API}/images/inspect", json={"image": "registry.example.com/shop/worker:2.5.0-rc1"}).json()
    assert {c["id"]: c["status"] for c in r["checks"]}["tag_exists"] == "fail"
    assert ctx.audit.search(action="image.inspect")["total"] == 2


def test_overview_issues_ha_search(admin, ctx):
    ov = admin.get(f"{API}/cluster/overview").json()
    assert ov["nodes"]["notReady"] == 1 and "notifications" in ov
    iss = admin.get(f"{API}/cluster/issues").json()
    assert iss["counts"]["CRITICAL"] >= 3 and iss["items"][0]["acknowledged"] is None
    assert all(i["severity"] == "WARNING" for i in admin.get(f"{API}/cluster/issues?severity=WARNING").json()["items"])
    assert {i["namespace"] for i in admin.get(f"{API}/cluster/issues?namespace=staging").json()["items"]} == {"staging"}
    # acknowledged notifications are reflected in the operations center
    ctx.monitor_once()
    n = admin.get(f"{API}/notifications").json()["items"][0]
    admin.post(f"{API}/notifications/{n['id']}/ack")
    acked = next(i for i in admin.get(f"{API}/cluster/issues").json()["items"] if i["id"] == n["fingerprint"])
    assert acked["acknowledged"]["by"] == "admin"
    ha = admin.get(f"{API}/cluster/ha").json()
    web = next(w for w in ha["workloads"] if w["name"] == "web-prod")
    assert web["pdb"] == "web-prod" and "no_pdb" not in web["flags"] and ha["readyNodes"] == 2
    api = next(w for w in ha["workloads"] if w["name"] == "api-prod")
    assert "no_pdb" in api["flags"]
    single = next(w for w in ha["workloads"] if w["name"] == "web-staging")
    assert "single_replica" in single["flags"]
    assert admin.get(f"{API}/cluster/ha?namespace=staging").json()["workloads"]
    s = admin.get(f"{API}/search", params={"q": "web"}).json()
    types = {x["type"] for x in s["items"]}
    assert "k8s" in types and s["items"][0]["name"].startswith("web")
    s = admin.get(f"{API}/search", params={"q": "nginx"}).json()
    assert any(x.get("match") == "image" for x in s["items"]) and any(x["type"] == "podman_image" for x in s["items"])
    s = admin.get(f"{API}/search", params={"q": "back-off"}).json()
    assert any(x["type"] == "event" for x in s["items"])
    assert any(x["type"] == "podman_container" for x in admin.get(f"{API}/search", params={"q": "proxy"}).json()["items"])
    assert admin.get(f"{API}/search", params={"q": "a"}).status_code == 422
