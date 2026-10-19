"""Podman, monitoring, notifications, health, status, audit, users, settings, backups, maintenance, live events."""

from __future__ import annotations

import time

from .conftest import API, PASSWORD, login
from .test_api_k8s import wait_op


# ------------------------------------------------------------------ podman
def test_podman_read(admin):
    info = admin.get(f"{API}/podman/info").json()
    assert info["connected"] and info["version"].endswith("demo")
    items = admin.get(f"{API}/podman/containers").json()["items"]
    assert {c["state"] for c in items} == {"running", "exited", "created"}
    running_only = admin.get(f"{API}/podman/containers", params={"all": False}).json()["items"]
    assert all(c["state"] == "running" for c in running_only)
    insp = admin.get(f"{API}/podman/containers/pg-reporting").json()["inspect"]
    assert insp["Name"] == "pg-reporting"
    assert admin.get(f"{API}/podman/containers/ghost").json()["error"]["code"] == "podman_not_found"
    assert admin.get(f"{API}/podman/containers/..%2Fx").status_code in (404, 422)
    logs = admin.get(f"{API}/podman/containers/report-builder/logs", params={"tail": 2}).json()
    assert logs["count"] == 2 and "exiting" in logs["lines"][-1]
    r = admin.get(f"{API}/podman/containers/edge-proxy/logs", params={"tail": 3, "download": True})
    assert "attachment" in r.headers["content-disposition"]
    imgs = admin.get(f"{API}/podman/images").json()
    assert imgs["count"] == 5 and any(i["dangling"] for i in imgs["items"])
    cfg = admin.get(f"{API}/podman/images/docker.io/library/nginx:1.27.2/config").json()
    assert cfg["config"]["os"] == "linux" and cfg["tags"]
    regs = admin.get(f"{API}/podman/registries").json()
    assert regs["connected"] and "docker.io" in regs["search"] and regs["imagesByRegistry"]["docker.io"] == 2
    assert admin.get(f"{API}/podman/stats").json()["items"][0]["cpuPercent"] >= 0


def test_podman_env_masking(admin, ctx):
    c = ctx.podman._containers[next(iter(ctx.podman._containers))]
    orig = ctx.podman.inspect_container

    def inspect(cid):
        d = orig(cid)
        d["Config"]["Env"] = ["DB_PASSWORD=x", "API_TOKEN=y", "PLAIN=z"]
        return d

    ctx.podman.inspect_container = inspect
    env = admin.get(f"{API}/podman/containers/{c['Names'][0]}").json()["inspect"]["Config"]["Env"]
    assert env == ["DB_PASSWORD=<hidden>", "API_TOKEN=<hidden>", "PLAIN=z"]


def test_podman_actions(admin, operator, ctx):
    base = f"{API}/podman/containers/edge-proxy"
    r = operator.post(f"{base}/action", json={"action": "stop"})
    assert r.status_code == 428 and r.json()["error"]["params"]["expected"] == "edge-proxy"
    assert operator.post(f"{base}/action", json={"action": "stop", "confirm": "edge-proxy"}).json() == {"ok": True}
    assert operator.post(f"{base}/action", json={"action": "start"}).json() == {"ok": True}
    assert operator.post(f"{base}/action", json={"action": "restart"}).json() == {"ok": True}
    assert operator.post(f"{base}/action", json={"action": "kill"}).status_code == 422
    r = operator.post(f"{API}/podman/containers/ghost/action", json={"action": "start"})
    assert r.status_code == 404 and ctx.audit.search(action="podman.container.start", result="failure")["total"] == 1
    assert operator.delete(f"{base}?confirm=edge-proxy").status_code == 403
    assert admin.delete(f"{base}").status_code == 428
    r = admin.delete(f"{base}?confirm=edge-proxy")
    assert r.status_code == 502 and "running" in r.json()["error"]["message"]
    assert admin.delete(f"{base}?confirm=edge-proxy&force=true").json() == {"ok": True}


def test_podman_images_manage(admin, ctx):
    r = admin.post(f"{API}/podman/images/pull", json={"reference": "docker.io/library/busybox:1.36"}).json()
    assert r["id"] and r["demo"]
    r = admin.post(f"{API}/podman/images/pull", json={"reference": "docker.io/library/notfound:1"})
    assert r.status_code == 502 and ctx.audit.search(action="podman.image.pull", result="failure")["total"] == 1
    ref = "docker.io/library/postgres:16.4"
    assert admin.delete(f"{API}/podman/images/{ref}").status_code == 428
    r = admin.delete(f"{API}/podman/images/{ref}", params={"confirm": ref})
    assert r.status_code == 502  # in use by pg-reporting
    assert admin.delete(f"{API}/podman/images/{ref}", params={"confirm": ref, "force": True}).json() == {"ok": True}


# ------------------------------------------------------------------ monitoring
def test_monitoring(admin, viewer):
    src = viewer.get(f"{API}/monitoring/sources").json()
    assert src["metricsServer"] and src["prometheus"] == {"configured": False, "ok": False}
    assert len(viewer.get(f"{API}/monitoring/nodes").json()["nodes"]) == 3
    pods = viewer.get(f"{API}/monitoring/pods", params={"namespace": "production", "sort": "memory", "limit": 2}).json()
    assert pods["metricsServer"] and len(pods["pods"]) == 2
    assert viewer.get(f"{API}/monitoring/storage").json()["pvcs"]
    r = viewer.get(f"{API}/monitoring/prometheus/cluster_cpu")
    assert r.status_code == 503 and r.json()["error"]["code"] == "metrics_unavailable"
    assert r.json()["error"]["params"]["reason"] == "not_configured"


def test_monitoring_with_prometheus(admin, ctx, monkeypatch):
    import httpx

    admin.put(f"{API}/settings/monitoring", json={"prometheus_url": "http://prom:9090"})

    def fake_get(url, params=None, **kw):
        if url.endswith("query_range"):
            return httpx.Response(200, json={"status": "success", "data": {"result": []}})
        return httpx.Response(200, json={"status": "success", "data": {"result": [
            {"metric": {"namespace": "staging", "persistentvolumeclaim": "uploads-staging"}, "value": [0, "0.5"]}]}})

    monkeypatch.setattr("pkm.monitoring.httpx.get", fake_get)
    assert admin.get(f"{API}/monitoring/sources").json()["prometheus"]["ok"]
    assert admin.get(f"{API}/monitoring/prometheus/node_cpu", params={"range": "6h"}).json()["series"] == []
    st = admin.get(f"{API}/monitoring/storage").json()
    assert st["usageSource"] == "prometheus"
    assert next(p for p in st["pvcs"] if p["name"] == "uploads-staging")["usedRatio"] == 0.5


# ------------------------------------------------------------------ notifications / stream
def test_notifications(admin, operator, viewer, ctx):
    r = admin.post(f"{API}/notifications/refresh").json()
    assert r["changed"] and r["counts"]["open"] > 0
    lst = viewer.get(f"{API}/notifications").json()
    assert lst["total"] == lst["counts"]["open"]
    crit = viewer.get(f"{API}/notifications", params={"severity": "CRITICAL"}).json()["items"]
    assert crit and all(n["severity"] == "CRITICAL" for n in crit)
    assert viewer.get(f"{API}/notifications", params={"q": "worker"}).json()["total"] >= 1
    nid = crit[0]["id"]
    assert viewer.post(f"{API}/notifications/{nid}/ack").status_code == 403
    assert operator.post(f"{API}/notifications/{nid}/ack").json()["status"] == "acknowledged"
    assert viewer.get(f"{API}/notifications", params={"status": "acknowledged"}).json()["total"] == 1
    assert operator.post(f"{API}/notifications/{nid}/unack").json()["status"] == "open"
    assert operator.post(f"{API}/notifications/999999/ack").status_code == 404
    assert ctx.audit.search(action="notification.ack")["total"] == 1
    assert viewer.get(f"{API}/notifications", params={"status": "bogus"}).status_code == 422


def test_event_stream(admin, ctx):
    with admin.stream("GET", f"{API}/stream") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = r.iter_lines()
        assert next(lines) == "event: hello"
        assert next(lines).startswith("data: ")


def test_event_bus_publish():
    import asyncio

    from pkm.context import EventBus

    async def run():
        bus = EventBus()
        q = bus.subscribe()
        bus.publish({"type": "x"})
        for _ in range(150):
            bus.publish({"type": "flood"})  # full queue never blocks the publisher
        assert bus.subscribers == 1
        data = await q.get()
        bus.unsubscribe(q)
        return data

    assert asyncio.run(run()) == '{"type": "x"}'


# ------------------------------------------------------------------ status / health
def test_status_and_health(admin, viewer):
    st = viewer.get(f"{API}/system/status").json()
    assert st["mode"] == "demo" and st["kubernetes"]["connected"] and st["podman"]["connected"]
    assert st["kubernetes"]["version"] == "v1.31.4-demo" and st["apiVersion"] == "v1"
    h = viewer.get(f"{API}/health").json()
    by = {c["id"]: c for c in h["checks"]}
    assert by["database"]["status"] == "healthy" and by["kubernetes"]["status"] == "healthy"
    assert by["configuration"]["status"] == "degraded" and "demo_mode" in by["configuration"]["params"]["problems"]
    assert by["prometheus"]["message"] == "not_configured" and by["backup"]["message"] == "never"
    assert h["status"] == "degraded"
    admin.post(f"{API}/backups", json={})
    time.sleep(1)
    assert {c["id"]: c for c in viewer.get(f"{API}/health").json()["checks"]}["backup"]["status"] == "healthy"


# ------------------------------------------------------------------ audit
def test_audit_api(admin, ctx):
    admin.post(f"{API}/k8s/deployments/production/web-prod/scale", json={"replicas": 2})
    res = admin.get(f"{API}/audit").json()
    assert res["total"] >= 2 and "workload.scale" in res["actions"] and res["retentionDays"] == 365
    e = admin.get(f"{API}/audit", params={"action": "workload.scale"}).json()["items"][0]
    assert e["detail"] == {"from": 3, "to": 2} and e["namespace"] == "production" and e["ip"] and e["request_id"]
    assert admin.get(f"{API}/audit/{e['id']}").json()["resource_name"] == "web-prod"
    assert admin.get(f"{API}/audit/999999").status_code == 404
    assert admin.get(f"{API}/audit", params={"result": "success", "username": "admin", "q": "web"}).json()["total"] >= 1
    csv_ = admin.get(f"{API}/audit/export.csv", params={"action": "workload"})
    assert csv_.headers["content-type"].startswith("text/csv") and "workload.scale" in csv_.text
    assert admin.get(f"{API}/audit", params={"action": "audit.export"}).json()["total"] == 1


# ------------------------------------------------------------------ users
def test_users_crud(app, admin, ctx):
    r = admin.post(f"{API}/users", json={"username": "bob", "password": PASSWORD, "role": "viewer",
                                         "must_change_password": False})
    uid = r.json()["user"]["id"]
    assert admin.post(f"{API}/users", json={"username": "bob", "password": PASSWORD, "role": "viewer"}).status_code == 409
    assert admin.post(f"{API}/users", json={"username": "x", "password": PASSWORD, "role": "god"}).status_code == 422
    assert len(admin.get(f"{API}/users").json()["items"]) == 2
    bob = login(app, "bob")
    u = admin.patch(f"{API}/users/{uid}", json={"role": "operator", "display_name": "Bob"}).json()["user"]
    assert u["role"] == "operator"
    entry = admin.get(f"{API}/audit", params={"action": "user.update"}).json()["items"][0]
    assert entry["detail"]["changes"]["role"] == {"from": "viewer", "to": "operator"}
    admin.patch(f"{API}/users/{uid}", json={"active": False})
    assert bob.get(f"{API}/auth/me").status_code == 401  # deactivation revokes sessions
    admin.patch(f"{API}/users/{uid}", json={"active": True})
    r = admin.post(f"{API}/users/{uid}/password", json={"password": "Temp0rary-Passw0rd", "must_change_password": True})
    assert r.json()["user"]["must_change_password"]
    assert admin.post(f"{API}/users/{uid}/unlock").json()["user"]["locked"] is False
    me = admin.get(f"{API}/auth/me").json()["user"]["id"]
    r = admin.patch(f"{API}/users/{me}", json={"role": "viewer"})
    assert r.status_code == 400 and r.json()["error"]["params"]["rule"] == "self"
    r = admin.delete(f"{API}/users/{me}?confirm=admin")
    assert r.status_code == 400
    assert admin.delete(f"{API}/users/{uid}").status_code == 428
    assert admin.delete(f"{API}/users/{uid}?confirm=bob").json() == {"ok": True}
    assert admin.delete(f"{API}/users/{uid}?confirm=bob").status_code == 404


# ------------------------------------------------------------------ settings
def test_settings(admin, operator, ctx):
    s = operator.get(f"{API}/settings").json()
    assert s["readonly"]["mode"] == "demo" and "kubernetes" in s["editable"]
    assert s["effective"]["logging"]["level"]["source"] == "file"
    r = admin.put(f"{API}/settings/logging", json={"level": "DEBUG"}).json()
    assert r["effective"]["logging"]["level"] == {"value": "DEBUG", "source": "ui", "editable": True}
    import logging

    assert logging.getLogger("pkm").level == logging.DEBUG
    r = admin.put(f"{API}/settings/logging", json={"level": "LOUD"})
    assert r.status_code == 422 and r.json()["error"]["params"]["errors"]
    assert admin.put(f"{API}/settings/server", json={"port": 1}).status_code == 422
    assert admin.put(f"{API}/settings/auth", json={"session_idle_minutes": 60}).status_code == 200
    assert ctx.users.cfg.session_idle_minutes == 60
    for section, values in (("podman", {"timeout": 5}), ("kubernetes", {"request_timeout": 15}),
                            ("backup", {"retention_count": 3})):
        assert admin.put(f"{API}/settings/{section}", json=values).status_code == 200
    assert ctx.settings.backup.retention_count == 3
    r = admin.delete(f"{API}/settings/logging").json()
    assert r["effective"]["logging"]["level"]["source"] == "file"
    assert ctx.audit.search(action="settings.update", result="failure")["total"] == 2
    assert ctx.audit.search(action="settings.reset")["total"] == 1


# ------------------------------------------------------------------ backups / maintenance
def test_backups(admin, operator, ctx):
    r = admin.post(f"{API}/backups", json={"include_manifests": True}).json()
    op = wait_op(admin, r["operation"]["id"])
    assert op["status"] == "succeeded", op
    fname = op["result"]["backup"]["filename"]
    assert "k8s_manifests" in op["result"]["backup"]["includes"]
    lst = operator.get(f"{API}/backups").json()
    assert lst["items"][0]["filename"] == fname and lst["items"][0]["present"] and lst["retentionCount"] == 14
    v = admin.post(f"{API}/backups/{fname}/verify").json()
    assert v["ok"] and v["manifest"]["notice"].startswith("Not a Kubernetes cluster backup")
    dl = admin.get(f"{API}/backups/{fname}/download")
    assert dl.headers["content-type"] == "application/gzip" and dl.content[:2] == b"\x1f\x8b"
    assert admin.get(f"{API}/backups/evil.tar.gz/download").status_code == 422
    assert admin.delete(f"{API}/backups/{fname}").status_code == 428
    assert admin.delete(f"{API}/backups/{fname}?confirm={fname}").json() == {"ok": True}
    assert admin.post(f"{API}/backups/{fname}/verify").status_code == 404
    actions = {e["action"] for e in admin.get(f"{API}/audit", params={"action": "backup"}).json()["items"]}
    assert actions == {"backup.create", "backup.verify", "backup.download", "backup.delete"}


def test_maintenance(admin):
    assert set(admin.post(f"{API}/maintenance/housekeeping").json()) == {"sessions", "audit", "notifications"}
    assert admin.post(f"{API}/maintenance/cache/clear").json() == {"ok": True}
    assert admin.post(f"{API}/maintenance/database/optimize").json() == {"integrity": "ok"}


def test_monitor_once_and_lifespan_loop(tmp_path):
    """The background monitor runs in the lifespan and publishes notifications."""
    from fastapi.testclient import TestClient

    from pkm.main import create_app

    from .conftest import make_settings

    app = create_app(make_settings(tmp_path, monitoring={"poll_interval_seconds": 10}), start_background=True)
    with TestClient(app):
        deadline = time.time() + 15
        while time.time() < deadline and app.state.ctx.last_monitor["at"] is None:
            time.sleep(0.2)
        assert app.state.ctx.last_monitor["issues"] > 0
    assert app.state.ctx.notifications.counts()["open"] > 0
