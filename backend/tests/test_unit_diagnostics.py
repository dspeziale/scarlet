"""Problem detection, summaries and relationship graphs on hand-built objects."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pkm.k8s import diagnostics, relations
from pkm.k8s.diagnostics import analyze, parse_image, summary_counts
from pkm.k8s.summarize import age_seconds, pod_health, pod_reason, summarize, top_owner


def ts(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def node(name="n1", ready=True, cpu="4", mem="8Gi", unschedulable=False, pressure=None, hb_minutes=0):
    conds = [{"type": "Ready", "status": "True" if ready else "Unknown", "lastHeartbeatTime": ts(minutes=hb_minutes),
              "message": "kubelet stopped" if not ready else ""}]
    if pressure:
        conds.append({"type": pressure, "status": "True", "message": f"{pressure} detected"})
    return {"kind": "Node", "metadata": {"name": name, "uid": f"u-{name}", "labels": {}},
            "spec": {"unschedulable": unschedulable} if unschedulable else {},
            "status": {"conditions": conds, "allocatable": {"cpu": cpu, "memory": mem}}}


def pod(name="p1", ns="default", *, waiting=None, last=None, phase="Running", ready=True, restarts=0, image="nginx:1.27",
        owner_rs=None, hash_="abc12", node_name="n1", spec_extra=None, conds=None, state=None, age_minutes=10,
        status_extra=None, container="app"):
    cs = {"name": container, "image": image, "ready": ready, "restartCount": restarts,
          "state": state or ({"waiting": waiting} if waiting else {"running": {"startedAt": ts(minutes=5)}})}
    if last:
        cs["lastState"] = {"terminated": last}
    meta = {"name": name, "namespace": ns, "uid": f"u-{name}", "creationTimestamp": ts(minutes=age_minutes),
            "labels": {"app": "web", "pod-template-hash": hash_}}
    if owner_rs:
        meta["ownerReferences"] = [{"kind": "ReplicaSet", "name": owner_rs, "uid": f"u-{owner_rs}", "controller": True}]
    spec = {"containers": [{"name": container, "image": image}], "nodeName": node_name}
    spec.update(spec_extra or {})
    status = {"phase": phase, "containerStatuses": [cs] if phase != "Pending" or waiting else [],
              "conditions": conds or [{"type": "Ready", "status": "True" if ready else "False"}]}
    status.update(status_extra or {})
    return {"kind": "Pod", "metadata": meta, "spec": spec, "status": status}


def event(kind, name, msg, reason="Failed", ns="default", etype="Warning"):
    return {"kind": "Event", "metadata": {"name": f"e-{name}-{reason}", "namespace": ns}, "type": etype,
            "reason": reason, "message": msg, "lastTimestamp": ts(minutes=1),
            "involvedObject": {"kind": kind, "name": name, "namespace": ns}}


def find(issues, reason):
    return next(i for i in issues if i.reason == reason)


def check(issue, cid):
    return next(c for c in issue.checks if c.id == cid)


# ------------------------------------------------------------------ summarize
def test_pod_reason_variants():
    assert pod_reason(pod(waiting={"reason": "CrashLoopBackOff"})) == "CrashLoopBackOff"
    p = pod()
    p["metadata"]["deletionTimestamp"] = ts()
    assert pod_reason(p) == "Terminating"
    p = pod(state={"terminated": {"reason": "Completed", "exitCode": 0}}, phase="Succeeded", ready=False)
    assert pod_reason(p) == "Completed"
    p = pod(state={"terminated": {"exitCode": 2}}, phase="Failed", ready=False)
    assert pod_reason(p) == "ExitCode:2"
    p = pod(state={"terminated": {"signal": 9}}, phase="Failed", ready=False)
    assert pod_reason(p) == "Signal:9"
    p = pod(phase="Pending", ready=False)
    p["spec"]["initContainers"] = [{"name": "init"}, {"name": "init2"}]
    p["status"]["initContainerStatuses"] = [{"name": "init", "state": {"terminated": {"exitCode": 0}}},
                                            {"name": "init2", "state": {"waiting": {"reason": "PodInitializing"}}}]
    assert pod_reason(p) == "Init:1/2"
    p["status"]["initContainerStatuses"][1]["state"] = {"waiting": {"reason": "CrashLoopBackOff"}}
    assert pod_reason(p) == "Init:CrashLoopBackOff"
    assert pod_health(p) == "failed"
    p["status"]["initContainerStatuses"][1]["state"] = {"terminated": {"exitCode": 1}}
    assert pod_reason(p) == "Init:Error"
    unsched = pod(phase="Pending", ready=False, node_name=None,
                  conds=[{"type": "PodScheduled", "status": "False", "reason": "Unschedulable"}])
    unsched["spec"].pop("nodeName")
    assert pod_reason(unsched) == "Pending"
    assert pod_health(unsched) == "pending"


def test_pod_health():
    assert pod_health(pod()) == "healthy"
    assert pod_health(pod(ready=False)) == "degraded"
    assert pod_health(pod(phase="Succeeded", state={"terminated": {"reason": "Completed", "exitCode": 0}})) == "completed"
    assert pod_health(pod(phase="Weird")) == "unknown"


def test_top_owner():
    assert top_owner(pod(owner_rs="web-abc12")) == {"kind": "Deployment", "name": "web"}
    assert top_owner(pod(owner_rs="other-rs")) == {"kind": "ReplicaSet", "name": "other-rs"}
    assert top_owner(pod()) is None
    p = pod()
    p["metadata"]["ownerReferences"] = [{"kind": "Job", "name": "j1"}]
    assert top_owner(p) == {"kind": "Job", "name": "j1"}
    p["metadata"]["ownerReferences"] = [{"kind": "StatefulSet", "name": "db", "controller": True}]
    assert top_owner(p) == {"kind": "StatefulSet", "name": "db"}


def test_age_seconds():
    assert age_seconds(None) is None
    assert age_seconds("bad") is None
    assert 50 < age_seconds(ts(minutes=1)) < 70


def test_summaries_all_kinds(demo):
    from pkm.k8s.kinds import KINDS

    for info in KINDS.values():
        for obj in demo.list(info):
            s = summarize(obj)
            assert s["kind"] == info.kind and s["health"]
    assert summarize({"kind": "Unknown", "metadata": {"name": "x"}})["health"] == "unknown"


def test_deployment_health_states():
    base = {"kind": "Deployment", "metadata": {"name": "d", "generation": 2},
            "spec": {"replicas": 3}, "status": {"availableReplicas": 3, "updatedReplicas": 3, "observedGeneration": 2}}
    assert summarize(base)["health"] == "healthy"
    d = {**base, "spec": {"replicas": 3, "paused": True}}
    assert summarize(d)["health"] == "suspended"
    d = {**base, "status": {"availableReplicas": 1, "updatedReplicas": 3}}
    assert summarize(d)["health"] == "degraded"
    d = {**base, "status": {"availableReplicas": 0}}
    assert summarize(d)["health"] == "failed"
    d = {**base, "status": {"availableReplicas": 3, "updatedReplicas": 1, "observedGeneration": 2}}
    assert summarize(d)["health"] == "progressing"
    d = {**base, "status": {**base["status"], "conditions": [{"type": "Progressing", "reason": "ProgressDeadlineExceeded"}]}}
    assert summarize(d)["health"] == "failed"
    assert summarize({**base, "spec": {"replicas": 0}})["health"] == "suspended"


def test_job_and_misc_summaries():
    job = {"kind": "Job", "metadata": {"name": "j"}, "spec": {"completions": 1},
           "status": {"failed": 2, "conditions": [{"type": "Failed", "status": "True", "reason": "BackoffLimitExceeded"}]}}
    s = summarize(job)
    assert s["health"] == "failed" and s["failReason"] == "BackoffLimitExceeded"
    job2 = {"kind": "Job", "metadata": {"name": "j"}, "spec": {"suspend": True}, "status": {}}
    assert summarize(job2)["health"] == "suspended"
    assert summarize({"kind": "Job", "metadata": {"name": "j"}, "spec": {}, "status": {}})["health"] == "progressing"
    lb = {"kind": "Service", "metadata": {"name": "s"}, "spec": {"type": "LoadBalancer", "ports": [{"port": 80, "nodePort": 30080}]}}
    s = summarize(lb)
    assert s["health"] == "pending" and s["ports"] == ["80:30080/TCP"]
    ep = {"kind": "Endpoints", "metadata": {"name": "e"}, "subsets": [{"notReadyAddresses": [{"ip": "1.1.1.1"}]}]}
    assert summarize(ep)["health"] == "degraded"
    assert summarize({"kind": "Endpoints", "metadata": {"name": "e"}})["health"] == "unknown"
    ns = {"kind": "Namespace", "metadata": {"name": "x"}, "status": {"phase": "Terminating"}}
    assert summarize(ns)["health"] == "progressing"
    pdb = {"kind": "PodDisruptionBudget", "metadata": {"name": "p"}, "spec": {}, "status": {"disruptionsAllowed": 0}}
    assert summarize(pdb)["health"] == "degraded"
    ev = {"kind": "Event", "metadata": {"name": "e", "creationTimestamp": "2026-01-01T00:00:00Z"}, "type": "Normal",
          "regarding": {"kind": "Pod", "name": "p"}, "note": "hello", "series": {"count": 4}}
    s = summarize(ev)
    assert s["message"] == "hello" and s["count"] == 4 and s["lastTimestamp"] == "2026-01-01T00:00:00Z"
    sts = {"kind": "StatefulSet", "metadata": {"name": "s"}, "spec": {"replicas": 2}, "status": {"readyReplicas": 1}}
    assert summarize(sts)["health"] == "degraded"
    ds = {"kind": "DaemonSet", "metadata": {"name": "d"}, "spec": {}, "status": {"desiredNumberScheduled": 2, "numberReady": 0}}
    assert summarize(ds)["health"] == "failed"


# ------------------------------------------------------------------ images
def test_parse_image():
    assert parse_image("nginx") == {"valid": True, "registry": "docker.io", "repository": "nginx", "tag": None, "digest": None}
    r = parse_image("library/nginx:1.27")
    assert r["registry"] == "docker.io" and r["repository"] == "library/nginx" and r["tag"] == "1.27"
    r = parse_image("registry.example.com:5000/team/app:2.0")
    assert r["registry"] == "registry.example.com:5000" and r["repository"] == "team/app"
    r = parse_image("localhost/app@sha256:" + "a" * 64)
    assert r["registry"] == "localhost" and r["digest"].startswith("sha256:")
    assert parse_image("UPPER/Case")["valid"] is False


# ------------------------------------------------------------------ diagnostics
def test_crashloop_exit_code():
    p = pod(waiting={"reason": "CrashLoopBackOff", "message": "back-off"}, ready=False, restarts=7,
            last={"exitCode": 127, "reason": "Error", "finishedAt": ts(minutes=1)}, owner_rs="web-abc12")
    i = find(analyze({"pods": [p]}), "CrashLoopBackOff")
    assert i.severity == "ERROR" and i.likely_cause == "exit_code"
    assert i.facts["exitMeaning"] == "command_not_found"
    assert i.owner == {"kind": "Deployment", "name": "web"}
    assert "view_previous_logs" in i.actions and i.guide == "crashloopbackoff"


def test_crashloop_liveness_and_oom():
    p = pod(waiting={"reason": "CrashLoopBackOff"}, ready=False, restarts=3, last={"exitCode": 137, "reason": "Error"})
    ev = event("Pod", "p1", "Liveness probe failed: HTTP probe failed with statuscode: 500", reason="Unhealthy")
    i = find(analyze({"pods": [p], "events": [ev]}), "CrashLoopBackOff")
    assert i.likely_cause == "liveness_probe"
    assert check(i, "liveness_probe").status == "fail"
    oom = pod(waiting={"reason": "CrashLoopBackOff"}, ready=False, last={"exitCode": 137, "reason": "OOMKilled"})
    oom["spec"]["containers"][0]["resources"] = {"limits": {"memory": "128Mi"}}
    i = find(analyze({"pods": [oom]}), "OOMKilled")
    assert i.severity == "ERROR" and check(i, "memory_limit_set").status == "ok"


def test_oomkilled_recovered_with_metrics():
    p = pod(restarts=2, last={"exitCode": 137, "reason": "OOMKilled", "finishedAt": ts(minutes=30)})
    p["spec"]["containers"][0]["resources"] = {"limits": {"memory": "100Mi"}}
    metrics = [{"metadata": {"name": "p1", "namespace": "default"}, "containers": [{"name": "app", "usage": {"memory": "95Mi"}}]}]
    i = find(analyze({"pods": [p], "pod_metrics": metrics}), "OOMKilled")
    assert i.severity == "WARNING"
    assert check(i, "memory_usage").status == "warn"
    p2 = pod(restarts=1, last={"exitCode": 137, "reason": "OOMKilled", "finishedAt": ts(minutes=30)})
    i2 = find(analyze({"pods": [p2]}), "OOMKilled")
    assert check(i2, "memory_limit_set").status == "warn" and check(i2, "memory_usage").status == "unknown"
    # old OOM kills are not reported
    p3 = pod(restarts=1, last={"exitCode": 137, "reason": "OOMKilled", "finishedAt": ts(hours=30)})
    assert not analyze({"pods": [p3]})


def test_imagepull_not_found():
    p = pod(waiting={"reason": "ImagePullBackOff", "message": "Back-off"}, ready=False, image="nginx:9.9.9")
    ev = event("Pod", "p1", 'Failed to pull image "nginx:9.9.9": manifest unknown')
    i = find(analyze({"pods": [p], "events": [ev]}), "ImagePullBackOff")
    assert i.likely_cause == "tag_exists" and check(i, "tag_exists").status == "fail"
    assert check(i, "registry_auth").status == "ok"  # docker.io is public
    assert "manifest unknown" in i.message


def test_imagepull_auth_unreachable_and_secrets():
    p = pod(waiting={"reason": "ErrImagePull"}, ready=False, image="registry.corp.local/app:1.0")
    ev = event("Pod", "p1", "pull access denied: unauthorized: authentication required")
    i = find(analyze({"pods": [p], "events": [ev]}), "ImagePullBackOff")
    assert i.likely_cause == "registry_auth"
    ev2 = event("Pod", "p1", "dial tcp: lookup registry.corp.local: no such host")
    i = find(analyze({"pods": [p], "events": [ev2]}), "ImagePullBackOff")
    assert i.likely_cause == "registry_reachable"
    i = find(analyze({"pods": [p]}), "ImagePullBackOff")
    assert check(i, "registry_auth").status == "warn"  # private registry without pull secret
    assert check(i, "tag_exists").status == "unknown"
    p["spec"]["imagePullSecrets"] = [{"name": "regcred"}]
    i = find(analyze({"pods": [p]}), "ImagePullBackOff")
    assert check(i, "registry_auth").status == "unknown"
    latest = pod(waiting={"reason": "ImagePullBackOff"}, ready=False, image="nginx")
    i = find(analyze({"pods": [latest]}), "ImagePullBackOff")
    assert check(i, "image_tag").status == "warn"
    digest = pod(waiting={"reason": "ImagePullBackOff"}, ready=False, image="nginx@sha256:" + "b" * 64)
    assert check(find(analyze({"pods": [digest]}), "ImagePullBackOff"), "image_tag").status == "ok"
    bad = pod(waiting={"reason": "InvalidImageName"}, ready=False, image="Bad Image")
    i = find(analyze({"pods": [bad]}), "ImagePullBackOff")
    assert i.likely_cause == "image_format"


def test_pending_capacity_taints_selector_pvc():
    p = pod(phase="Pending", ready=False, node_name=None,
            conds=[{"type": "PodScheduled", "status": "False", "reason": "Unschedulable",
                    "message": "0/2 nodes are available: 2 Insufficient memory, 1 node(s) had untolerated taint"}])
    p["spec"].pop("nodeName")
    p["spec"]["containers"][0]["resources"] = {"requests": {"cpu": "100m", "memory": "64Gi"}}
    i = find(analyze({"pods": [p], "nodes": [node()]}), "Pending")
    assert i.severity == "WARNING" and i.likely_cause == "memory_capacity"
    assert check(i, "taints").status == "warn" and check(i, "cpu_capacity").status == "ok"
    p["spec"]["containers"][0]["resources"] = {"requests": {"cpu": "16"}}
    p["status"]["conditions"][0]["message"] = "0/1 nodes are available: 1 Insufficient cpu"
    assert find(analyze({"pods": [p], "nodes": [node()]}), "Pending").likely_cause == "cpu_capacity"
    p["spec"]["containers"][0]["resources"] = {}
    p["status"]["conditions"][0]["message"] = "0/1 nodes are available: 1 node(s) didn't match Pod's node affinity/selector"
    assert find(analyze({"pods": [p], "nodes": [node()]}), "Pending").likely_cause == "node_selector"
    p["status"]["conditions"][0]["message"] = "pod has unbound immediate PersistentVolumeClaims"
    p["spec"]["volumes"] = [{"name": "d", "persistentVolumeClaim": {"claimName": "data"}}]
    i = find(analyze({"pods": [p], "nodes": [node()], "pvcs": []}), "Pending")
    assert i.likely_cause == "volumes_bound" and check(i, "volumes_bound").params["claims"] == ["data"]
    p["status"]["conditions"][0]["message"] = "exceeded quota: compute"
    p["spec"].pop("volumes")
    assert find(analyze({"pods": [p], "nodes": [node()]}), "Pending").likely_cause == "quota"
    i = find(analyze({"pods": [p], "nodes": [node(ready=False)]}), "Pending")
    assert i.likely_cause == "schedulable_nodes"


def test_pending_young_pod_not_reported():
    p = pod(phase="Pending", ready=False, age_minutes=0, conds=[{"type": "PodScheduled", "status": "True"}])
    assert not [i for i in analyze({"pods": [p]}) if i.reason == "Pending"]


def test_create_container_config_error():
    p = pod(waiting={"reason": "CreateContainerConfigError", "message": 'configmap "cfg" not found'}, ready=False)
    c = p["spec"]["containers"][0]
    c["envFrom"] = [{"configMapRef": {"name": "cfg"}}, {"secretRef": {"name": "sec"}},
                    {"configMapRef": {"name": "opt", "optional": True}}]
    c["env"] = [{"name": "X", "valueFrom": {"secretKeyRef": {"name": "sec2", "key": "k"}}},
                {"name": "Y", "valueFrom": {"configMapKeyRef": {"name": "cfg2", "key": "k"}}}]
    p["spec"]["volumes"] = [{"name": "v", "configMap": {"name": "cfg3"}}, {"name": "s", "secret": {"secretName": "sec3"}}]
    snap = {"pods": [p], "configmaps": [{"metadata": {"name": "cfg2", "namespace": "default"}}],
            "secrets": [{"metadata": {"name": "sec", "namespace": "default"}}]}
    i = find(analyze(snap), "CreateContainerConfigError")
    assert i.likely_cause == "configmaps_exist"
    assert check(i, "configmaps_exist").params["missing"] == ["cfg", "cfg3"]
    assert check(i, "secrets_exist").params["missing"] == ["sec2", "sec3"]
    snap["configmaps"] += [{"metadata": {"name": n, "namespace": "default"}} for n in ("cfg", "cfg3")]
    snap["secrets"] += [{"metadata": {"name": n, "namespace": "default"}} for n in ("sec2", "sec3")]
    p["status"]["containerStatuses"][0]["state"]["waiting"]["message"] = "couldn't find key k in Secret"
    assert find(analyze(snap), "CreateContainerConfigError").likely_cause == "keys_exist"
    # without configmap/secret lists no checks are claimed
    assert find(analyze({"pods": [p]}), "CreateContainerConfigError").checks == []


def test_failed_unknown_and_other():
    failed = pod(phase="Failed", ready=False, state={"terminated": {"exitCode": 0}}, status_extra={"reason": "Evicted"})
    i = find(analyze({"pods": [failed], "nodes": [node()]}), "PodFailed")
    assert i.severity == "ERROR" and check(i, "node_ready").status == "ok"
    unknown = pod(phase="Unknown", ready=False)
    i = find(analyze({"pods": [unknown], "nodes": [node(ready=False)]}), "PodUnknown")
    assert i.severity == "WARNING" and i.likely_cause == "node_ready"
    other = pod(waiting={"reason": "RunContainerError"}, ready=False)
    assert find(analyze({"pods": [other]}), "RunContainerError").guide == "troubleshooting"


def test_high_restarts():
    p = pod(restarts=9, last={"exitCode": 1, "reason": "Error", "finishedAt": ts(minutes=5)})
    i = find(analyze({"pods": [p]}), "HighRestarts")
    assert i.severity == "WARNING"


def test_grouping_by_application():
    pods = [pod(name=f"web-abc12-{i}", waiting={"reason": "CrashLoopBackOff"}, ready=False, owner_rs="web-abc12")
            for i in range(3)]
    issues = [i for i in analyze({"pods": pods}) if i.reason == "CrashLoopBackOff"]
    assert len(issues) == 1 and len(issues[0].affected) == 3 and issues[0].facts["podCount"] == 3


def test_nodes():
    issues = analyze({"nodes": [node("a", ready=False, hb_minutes=10), node("b", pressure="DiskPressure"),
                                node("c", unschedulable=True)], "pods": [pod(node_name="a")]})
    nr = find(issues, "NodeNotReady")
    assert nr.severity == "CRITICAL" and nr.likely_cause == "kubelet_heartbeat" and nr.facts["podsOnNode"] == 1
    assert find(issues, "NodePressure").facts["condition"] == "DiskPressure"
    assert find(issues, "NodeCordoned").severity == "INFO"
    i = find(analyze({"nodes": [node("x", ready=False, pressure="MemoryPressure")]}), "NodeNotReady")
    assert i.likely_cause == "node_pressure"


def test_workloads_and_jobs():
    dep = lambda name, desired, avail, **kw: {"kind": "Deployment", "metadata": {"name": name, "namespace": "p"},  # noqa: E731
                                               "spec": {"replicas": desired, **kw},
                                               "status": {"availableReplicas": avail,
                                                          "conditions": [{"type": "Available", "status": "False",
                                                                          "message": "min availability"}]}}
    stuck = dep("stuck", 2, 2)
    stuck["status"]["conditions"].append({"type": "Progressing", "reason": "ProgressDeadlineExceeded", "message": "deadline"})
    snap = {"deployments": [dep("down", 3, 0), dep("half", 4, 1), dep("most", 4, 3), dep("ok", 2, 2),
                            dep("paused", 1, 1, paused=True), stuck],
            "statefulsets": [{"kind": "StatefulSet", "metadata": {"name": "db", "namespace": "p"}, "spec": {"replicas": 2},
                              "status": {"readyReplicas": 0}},
                             {"kind": "StatefulSet", "metadata": {"name": "db2", "namespace": "p"}, "spec": {"replicas": 2},
                              "status": {"readyReplicas": 1}}],
            "daemonsets": [{"kind": "DaemonSet", "metadata": {"name": "ds", "namespace": "p"},
                            "status": {"desiredNumberScheduled": 3, "numberReady": 0}},
                           {"kind": "DaemonSet", "metadata": {"name": "ds2", "namespace": "p"},
                            "status": {"desiredNumberScheduled": 3, "numberReady": 2}}],
            "jobs": [{"kind": "Job", "metadata": {"name": "j", "namespace": "p"}, "status": {"failed": 3, "conditions": [
                {"type": "Failed", "status": "True", "reason": "BackoffLimitExceeded", "lastTransitionTime": ts(hours=1)}]}},
                {"kind": "Job", "metadata": {"name": "old", "namespace": "p"}, "status": {"conditions": [
                    {"type": "Failed", "status": "True", "lastTransitionTime": ts(days=10)}]}}]}
    issues = analyze(snap)
    by = {(i.kind, i.name): i for i in issues}
    assert by[("Deployment", "down")].severity == "CRITICAL" and by[("Deployment", "down")].message == "min availability"
    assert by[("Deployment", "half")].severity == "ERROR"
    assert by[("Deployment", "most")].severity == "WARNING"
    assert ("Deployment", "ok") not in by
    assert by[("Deployment", "paused")].reason == "DeploymentPaused"
    assert by[("Deployment", "stuck")].reason == "RolloutStuck" and by[("Deployment", "stuck")].message == "deadline"
    assert by[("StatefulSet", "db")].severity == "CRITICAL" and by[("StatefulSet", "db2")].severity == "ERROR"
    assert by[("DaemonSet", "ds")].severity == "ERROR" and by[("DaemonSet", "ds2")].severity == "WARNING"
    assert by[("Job", "j")].reason == "JobFailed" and ("Job", "old") not in by
    # sorted by severity
    assert [i.severity for i in issues] == sorted([i.severity for i in issues], key=diagnostics.SEVERITY_ORDER.get)
    counts = summary_counts(issues)
    assert counts["CRITICAL"] == 2 and sum(counts.values()) == len(issues)


def test_pvc_pending():
    old = ts(minutes=10)
    pvc = lambda name, sc, phase="Pending": {"kind": "PersistentVolumeClaim", "metadata": {"name": name, "namespace": "d",  # noqa: E731
                                                                                         "creationTimestamp": old},
                                             "spec": {"storageClassName": sc, "resources": {"requests": {"storage": "1Gi"}}},
                                             "status": {"phase": phase}}
    scs = [{"metadata": {"name": "wffc", "annotations": {"storageclass.kubernetes.io/is-default-class": "true"}},
            "volumeBindingMode": "WaitForFirstConsumer"}]
    ev = event("PersistentVolumeClaim", "missing", 'storageclass.storage.k8s.io "fast" not found', "ProvisioningFailed", ns="d")
    young = pvc("young", "wffc")
    young["metadata"]["creationTimestamp"] = ts()
    issues = analyze({"pvcs": [pvc("missing", "fast"), pvc("waiting", "wffc"), pvc("default", None), pvc("lost", "wffc", "Lost"),
                               young, pvc("bound", "wffc", "Bound")],
                      "storageclasses": scs, "events": [ev]})
    by = {i.name: i for i in issues}
    assert by["missing"].severity == "WARNING" and by["missing"].likely_cause == "storage_class_exists"
    assert by["waiting"].severity == "INFO"
    assert check(by["waiting"], "waiting_first_consumer").status == "warn"
    assert by["default"].facts["storageClass"] == "wffc"
    assert by["lost"].severity == "ERROR" and by["lost"].reason == "PVCLost"
    assert "young" not in by and "bound" not in by


def test_demo_cluster_issue_set(demo):
    from pkm.config import KubernetesConfig
    from pkm.k8s.service import KubernetesService

    svc = KubernetesService(demo, KubernetesConfig())
    issues, partial = svc.issues()
    reasons = {i.reason for i in issues}
    assert {"NodeNotReady", "WorkloadUnavailable", "CrashLoopBackOff", "ImagePullBackOff", "OOMKilled", "Pending",
            "PVCPending", "PodUnknown"} <= reasons
    assert partial == []
    d = issues[0].to_dict()
    assert isinstance(d["checks"], list)
    svc.close()


# ------------------------------------------------------------------ relations
def test_relations_deployment(demo):
    from pkm.config import KubernetesConfig
    from pkm.k8s.service import KubernetesService

    svc = KubernetesService(demo, KubernetesConfig())
    g = svc.relations("deployments", "web-prod", "production")
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"Deployment", "ReplicaSet", "Pod", "Service", "Ingress", "Node", "ConfigMap"} <= kinds
    types = {e["type"] for e in g["edges"]}
    assert {"owns", "selects", "routes", "runs_on", "mounts"} <= types
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["from"] in ids and e["to"] in ids for e in g["edges"])
    assert any(n.get("root") for n in g["nodes"])
    for key, name, ns in [("services", "web-prod", "production"), ("ingresses", "shop", "production"),
                          ("statefulsets", "redis", "production"), ("persistentvolumeclaims", "data-redis-0", "production"),
                          ("configmaps", "web-config", "production"), ("secrets", "api-credentials", "production"),
                          ("nodes", "node-02", None), ("cronjobs", "db-backup", "production"),
                          ("daemonsets", "kube-proxy", "kube-system")]:
        g = svc.relations(key, name, ns)
        assert len(g["nodes"]) >= 2, key
    pods = demo.list(svc_kind("pods"), "production")
    g = svc.relations("pods", pods[0]["metadata"]["name"], "production")
    assert any(n["kind"] == "Deployment" for n in g["nodes"])
    svc.close()


def svc_kind(key):
    from pkm.k8s.kinds import KINDS

    return KINDS[key]


def test_relations_missing_refs_and_pv():
    pod_ = pod(name="p", ns="x")
    pod_["spec"]["volumes"] = [{"name": "c", "persistentVolumeClaim": {"claimName": "ghost"}},
                               {"name": "s", "secret": {"secretName": "nosuch"}}]
    pod_["spec"]["containers"][0]["envFrom"] = [{"configMapRef": {"name": "nocm"}}]
    g = relations.build(pod_, {"pods": [pod_]})
    missing = {n["name"] for n in g["nodes"] if n["missing"]}
    assert {"ghost", "nosuch", "nocm", "n1"} <= missing
    pv = {"kind": "PersistentVolume", "metadata": {"name": "pv1"}, "spec": {"claimRef": {"name": "c1", "namespace": "x"}}}
    g = relations.build(pv, {"pvcs": []})
    assert any(n["name"] == "c1" and n["missing"] for n in g["nodes"])
