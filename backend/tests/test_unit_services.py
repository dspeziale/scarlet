"""Database-backed services: users and sessions, audit, notifications, runtime settings, backup, operations, metrics."""

from __future__ import annotations

import io
import tarfile
import threading
import time
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from pkm.audit import AuditContext, AuditService
from pkm.backup import BackupService, restore_archive
from pkm.config import AuthConfig, MonitoringConfig, Settings
from pkm.db import Database, iso, parse_iso, utcnow
from pkm.errors import BadRequest, Conflict, MetricsUnavailable, NotFound, ValidationFailed
from pkm.monitoring import Prometheus
from pkm.notifications import NotificationService
from pkm.operations import OperationManager
from pkm.runtime_settings import RuntimeSettings
from pkm.security.users import LoginResult, UserService, check_setup_token, csrf_matches, new_setup_token

PW = "Str0ng-Passw0rd!"


@pytest.fixture
def db(tmp_path) -> Database:
    d = Database(str(tmp_path / "t.db"))
    d.migrate()
    return d


@pytest.fixture
def users(db) -> UserService:
    return UserService(db, AuthConfig(login_max_attempts=3, lockout_minutes=5))


# ------------------------------------------------------------------ db
def test_migrate_idempotent(db):
    assert db.migrate() == 1 and db.schema_version() == 1
    db.set_state("k", "v")
    assert db.get_state("k") == "v"
    db.set_state("k", None)
    assert db.get_state("k") is None
    assert parse_iso(None) is None and parse_iso("2026-01-01T00:00:00").tzinfo is not None


def test_transaction_rollback(db):
    with pytest.raises(RuntimeError), db.transaction() as c:
        c.execute("INSERT INTO app_state(key, value) VALUES ('x', '1')")
        raise RuntimeError
    assert db.get_state("x") is None


# ------------------------------------------------------------------ users
def test_create_and_validation(users):
    u = users.create("alice", PW, "operator", display_name="Alice", email="a@x", language="en")
    assert u.public()["role"] == "operator" and not u.public()["locked"]
    with pytest.raises(Conflict):
        users.create("ALICE", PW, "viewer")
    for args in (("bad name", PW, "viewer"), ("bob", PW, "root"), ("bob", "short", "viewer")):
        with pytest.raises(ValidationFailed):
            users.create(*args)
    with pytest.raises(ValidationFailed):
        users.create("bob", PW, "viewer", language="fr")
    assert users.count() == 1 and users.get_by_username("nobody") is None
    with pytest.raises(NotFound):
        users.get(999)


def test_authenticate_and_lockout(users):
    users.create("alice", PW, "admin")
    res, u = users.authenticate("alice", PW)
    assert res == LoginResult.OK and u.last_login_at
    assert users.authenticate("ghost", PW) == (LoginResult.INVALID, None)
    assert users.authenticate("alice", "wrong")[0] == LoginResult.INVALID
    assert users.authenticate("alice", "wrong")[0] == LoginResult.INVALID
    assert users.authenticate("alice", "wrong")[0] == LoginResult.LOCKED
    assert users.authenticate("alice", PW)[0] == LoginResult.LOCKED  # even with the right password
    assert users.get_by_username("alice").public()["locked"]
    users.unlock(users.get_by_username("alice").id)
    assert users.authenticate("alice", PW)[0] == LoginResult.OK


def test_disabled_user(users):
    a = users.create("admin", PW, "admin")
    b = users.create("bob", PW, "viewer")
    users.update(b.id, actor_id=a.id, active=False)
    assert users.authenticate("bob", PW)[0] == LoginResult.DISABLED


def test_sessions_lifecycle(users, db):
    u = users.create("alice", PW, "admin")
    token, s = users.create_session(u, "1.2.3.4", "ua")
    assert users.resolve_session(token).user.id == u.id
    assert users.resolve_session("nope") is None and users.resolve_session("") is None
    assert users.resolve_session("x" * 300) is None
    assert csrf_matches(s.csrf_token, s.csrf_token) and not csrf_matches(s.csrf_token, None)
    assert len(users.list_sessions(u.id)) == 1
    # idle expiry
    with db.connect() as c:
        c.execute("UPDATE sessions SET last_seen_at = ?", (iso(utcnow() - timedelta(hours=2)),))
    assert users.resolve_session(token) is None
    # absolute expiry
    token, s = users.create_session(u, "", "")
    with db.connect() as c:
        c.execute("UPDATE sessions SET expires_at = ?", (iso(utcnow() - timedelta(seconds=1)),))
    assert users.resolve_session(token) is None
    # purge + revoke
    users.create_session(u, "", "")
    _, s2 = users.create_session(u, "", "")
    assert users.revoke_user_sessions(u.id, except_session=s2.id) == 1
    with db.connect() as c:
        c.execute("UPDATE sessions SET last_seen_at = ?", (iso(utcnow() - timedelta(hours=2)),))
    assert users.purge_expired_sessions() == 1
    _, s3 = users.create_session(u, "", "")
    users.delete_session(s3.id)
    assert users.list_sessions(u.id) == []


def test_last_admin_and_self_protection(users):
    a = users.create("admin", PW, "admin")
    b = users.create("bob", PW, "operator")
    with pytest.raises(BadRequest):
        users.update(a.id, actor_id=a.id, role="viewer")
    with pytest.raises(BadRequest):
        users.update(a.id, actor_id=b.id, active=False)  # last active admin
    with pytest.raises(BadRequest):
        users.delete(a.id, actor_id=a.id)
    with pytest.raises(BadRequest):
        users.delete(a.id, actor_id=b.id)
    users.update(b.id, actor_id=a.id, role="admin")
    users.delete(a.id, actor_id=b.id)
    assert users.count() == 1
    assert users.update(b.id, actor_id=b.id) == users.get(b.id)
    with pytest.raises(ValidationFailed):
        users.update(b.id, actor_id=b.id, role="god")
    with pytest.raises(ValidationFailed):
        users.update(b.id, actor_id=b.id, language="de")


def test_passwords_change(users):
    u = users.create("alice", PW, "admin", must_change_password=True)
    token, _ = users.create_session(u, "", "")
    with pytest.raises(ValidationFailed):
        users.change_own_password(u.id, "wrong", "N3w-Passw0rd-OK")
    with pytest.raises(ValidationFailed):
        users.change_own_password(u.id, PW, PW)
    users.change_own_password(u.id, PW, "N3w-Passw0rd-OK")
    assert users.resolve_session(token) is None  # sessions revoked
    assert not users.get(u.id).must_change_password
    assert users.authenticate("alice", "N3w-Passw0rd-OK")[0] == LoginResult.OK


def test_setup_token(db):
    assert not check_setup_token(db, "x")
    t = new_setup_token(db)
    assert check_setup_token(db, t) and check_setup_token(db, f" {t} ") and not check_setup_token(db, "bad")
    assert not check_setup_token(db, None)


# ------------------------------------------------------------------ audit
def test_audit_scrub_search_purge(db):
    a = AuditService(db)
    ctx = AuditContext(1, "alice", "1.1.1.1", "ua", "ref", "rid")
    a.record(ctx, "user.create", kind="User", name="bob", detail={"password": "x", "nested": {"token": "t", "ok": 1}})
    a.record(ctx, "workload.scale", kind="Deployment", name="web", namespace="prod", result="failure")
    a.record(AuditContext(None, "carol"), "auth.login", result="denied")
    res = a.search()
    assert res["total"] == 3
    entry = a.get(res["items"][-1]["id"])
    assert entry["detail"] == {"password": "<redacted>", "nested": {"token": "<redacted>", "ok": 1}}
    assert a.search(username="alice")["total"] == 2
    assert a.search(action="workload")["total"] == 1
    assert a.search(result="denied")["total"] == 1
    assert a.search(q="web")["total"] == 1
    assert a.search(namespace="prod", kind="Deployment")["total"] == 1
    assert a.search(since="2000-01-01", until="2999-01-01")["total"] == 3
    assert a.search(limit=10_000)["limit"] == 500
    assert a.get(999) is None
    assert set(a.distinct_actions()) == {"user.create", "workload.scale", "auth.login"}
    with db.connect() as c:
        c.execute("UPDATE audit_log SET ts = ? WHERE username = 'carol'", (iso(utcnow() - timedelta(days=400)),))
    assert a.purge(365) == 1


# ------------------------------------------------------------------ notifications
def test_notifications_lifecycle(db):
    n = NotificationService(db)
    item = {"fingerprint": "f1", "severity": "ERROR", "reason": "CrashLoopBackOff", "kind": "Pod", "name": "p",
            "namespace": "d", "message": "m", "data": {"x": 1}}
    assert n.sync("kubernetes", [item]) == {"new": 1, "reopened": 0, "resolved": 0}
    assert n.sync("kubernetes", [item]) == {"new": 0, "reopened": 0, "resolved": 0}
    nid = n.list()["items"][0]["id"]
    assert n.list()["items"][0]["occurrences"] == 2
    acked = n.set_ack(nid, "alice", True)
    assert acked["status"] == "acknowledged" and acked["acknowledged_by"] == "alice"
    assert n.counts()["acknowledged"] == 1
    assert n.set_ack(nid, "", False)["status"] == "open"
    assert n.sync("kubernetes", []) == {"new": 0, "reopened": 0, "resolved": 1}
    assert n.list(status="active")["total"] == 0 and n.list(status="resolved")["total"] == 1
    assert n.sync("kubernetes", [item])["reopened"] == 1
    assert n.list(severity="ERROR", q="Crash")["total"] == 1
    # other sources are not resolved by a kubernetes sync
    n.sync("system", [{**item, "fingerprint": "s1", "severity": "CRITICAL"}])
    n.sync("kubernetes", [item])
    assert n.counts()["bySeverity"]["CRITICAL"] == 1
    with pytest.raises(NotFound):
        n.set_ack(999, "x", True)
    n.sync("kubernetes", [])
    with db.connect() as c:
        c.execute("UPDATE notifications SET resolved_at = ? WHERE status='resolved'", (iso(utcnow() - timedelta(days=40)),))
    assert n.purge_resolved(30) == 1


# ------------------------------------------------------------------ runtime settings
def test_runtime_settings(db):
    rs = RuntimeSettings(db, Settings())
    eff = rs.update("monitoring", {"prometheus_url": "http://prom:9090"}, "alice")
    assert eff.monitoring.prometheus_url == "http://prom:9090"
    d = rs.describe()
    assert d["monitoring"]["prometheus_url"] == {"value": "http://prom:9090", "source": "ui", "editable": True}
    assert d["server"]["port"]["editable"] is False
    with pytest.raises(ValidationFailed):
        rs.update("server", {"port": 1}, "a")
    with pytest.raises(ValidationFailed):
        rs.update("monitoring", {"prometheus_token": "x"}, "a")
    with pytest.raises(ValidationFailed) as e:
        rs.update("auth", {"session_idle_minutes": 1}, "a")
    assert e.value.params["errors"][0]["field"].endswith("session_idle_minutes")
    assert rs.reset("monitoring", "a").monitoring.prometheus_url is None


def test_secret_masked_in_describe(db):
    rs = RuntimeSettings(db, Settings(monitoring={"prometheus_token": "s3cret"}))
    assert rs.describe()["monitoring"]["prometheus_token"]["value"] == "********"


# ------------------------------------------------------------------ backup
@pytest.fixture
def backup_env(tmp_path, db):
    cfg = tmp_path / "etc" / "config.yaml"
    cfg.parent.mkdir()
    cfg.write_text("mode: live\n", encoding="utf-8")
    (cfg.parent / "pkm.env").write_text("PKM_X=1\n", encoding="utf-8")
    db.set_state("marker", "original")
    return BackupService(db, str(tmp_path / "backups"), str(cfg)), cfg


def test_backup_create_verify_restore(tmp_path, db, backup_env, demo):
    from pkm.config import KubernetesConfig
    from pkm.k8s.service import KubernetesService

    svc, cfg = backup_env
    k8s = KubernetesService(demo, KubernetesConfig())
    steps = []
    res = svc.create(trigger="manual", user="alice", include_manifests=True, k8s=k8s,
                     progress=lambda s, d: steps.append(s))
    assert res["status"] == "success" and res["includes"] == ["database", "config", "k8s_manifests"]
    assert steps == ["database", "config", "k8s_manifests"]
    path = svc.file_path(res["filename"])
    with tarfile.open(path) as tar:
        names = tar.getnames()
    assert "pkm.db" in names and "config/pkm.env" in names
    assert any(n.startswith("k8s/production/deployments/") for n in names)
    assert not any("/secrets/" in n or n.startswith("k8s/kube-system") for n in names)
    v = svc.verify(res["filename"])
    assert v["ok"] and {c["id"] for c in v["checks"]} >= {"archive_checksum", "file_checksums", "database_integrity"}
    assert svc.last()["filename"] == res["filename"]
    # restore over a modified database
    db.set_state("marker", "changed")
    cfg.write_text("mode: changed\n", encoding="utf-8")
    out = restore_archive(path, db.path, config_dir=str(cfg.parent), with_config=True)
    assert db.get_state("marker") == "original"
    assert cfg.read_text(encoding="utf-8") == "mode: live\n"
    assert any(p.name.endswith(out["previous_suffix"]) for p in Path(db.path).parent.iterdir())
    k8s.close()


def test_backup_tampered_and_unsafe(tmp_path, backup_env):
    svc, _ = backup_env
    res = svc.create(trigger="scheduled", user="cli")
    assert "-scheduled" in res["filename"]
    path = svc.file_path(res["filename"])
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    v = svc.verify(res["filename"])
    assert not v["ok"]
    assert svc.get(res["filename"])["verify_result"] == "failed"
    with pytest.raises(BadRequest):
        restore_archive(path, str(tmp_path / "x.db"), config_dir=None, with_config=False)
    # archive with a path traversal entry
    evil = tmp_path / "backups" / "pkm-backup-20260101T000000Z.tar.gz"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo("../evil.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    evil.write_bytes(buf.getvalue())
    v = svc.verify_file(evil)
    assert not v["ok"] and v["checks"][-1]["id"] == "archive_readable"
    assert not (tmp_path / "evil.txt").exists()
    # an archive dropped by hand is listed as external
    assert any(r["filename"] == evil.name and r["trigger"] == "external" for r in svc.list())


def test_backup_retention_and_names(tmp_path, backup_env, monkeypatch):
    svc, _ = backup_env
    names = []
    for i in range(3):
        import pkm.backup as b

        class FakeDT(b.datetime):
            @classmethod
            def now(cls, tz=None, _i=i):
                return b.datetime(2026, 1, 1, 0, 0, _i, tzinfo=tz)

        monkeypatch.setattr(b, "datetime", FakeDT)
        names.append(svc.create(trigger="manual", user="a")["filename"])
    removed = svc.apply_retention(2)
    assert removed == [names[0]]
    assert not (tmp_path / "backups" / names[0]).exists()
    with pytest.raises(ValidationFailed):
        svc.file_path("../../etc/passwd")
    with pytest.raises(NotFound):
        svc.file_path("pkm-backup-20990101T000000Z.tar.gz")
    with pytest.raises(NotFound):
        svc.get("pkm-backup-20990101T000000Z.tar.gz")
    svc.delete(names[2])
    assert [r["filename"] for r in svc.list() if r["status"] != "deleted"] == [names[1]]


def test_backup_failure_recorded(tmp_path, db, monkeypatch):
    svc = BackupService(db, str(tmp_path / "b"), None)
    monkeypatch.setattr(db, "backup_to", lambda target: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        svc.create(trigger="manual", user="a")
    with db.connect() as c:
        row = c.execute("SELECT status, detail FROM backups").fetchone()
    assert row["status"] == "failed" and "disk full" in row["detail"]


# ------------------------------------------------------------------ operations
def test_operations_manager():
    om = OperationManager()
    gate = threading.Event()
    done = []

    def work(op):
        op.progress("step", {"n": 1})
        gate.wait(2)
        return {"ok": True}

    op = om.start("drain", "n1", "alice", work, lambda o: done.append(o.status))
    with pytest.raises(Conflict):
        om.start("drain", "n1", "alice", work)
    gate.set()
    for _ in range(100):
        if op.status != "running":
            break
        time.sleep(0.02)
    assert op.status == "succeeded" and op.result == {"ok": True} and done == ["succeeded"]
    assert om.get(op.id).public()["steps"][0]["step"] == "step"
    from pkm.errors import K8sTimeout

    def fail(op):
        raise K8sTimeout("slow")

    def crash(op):
        raise RuntimeError("bug")

    for fn, code in ((fail, "k8s_timeout"), (crash, "internal_error")):
        o = om.start("x", fn.__name__, "a", fn)
        for _ in range(100):
            if o.status != "running":
                break
            time.sleep(0.02)
        assert o.status == "failed" and o.error["code"] == code

    def cancellable(op):
        while not op.cancelled():
            time.sleep(0.01)

    o = om.start("y", "t", "a", cancellable)
    om.cancel(o.id)
    for _ in range(100):
        if o.status != "running":
            break
        time.sleep(0.02)
    assert o.status == "cancelled"
    assert len(om.list()) == 4
    with pytest.raises(NotFound):
        om.get("nope")
    om.cancel_all()


# ------------------------------------------------------------------ prometheus
def test_prometheus(monkeypatch):
    p = Prometheus(MonitoringConfig())
    assert not p.configured
    with pytest.raises(MetricsUnavailable) as e:
        p.query("cluster_cpu")
    assert e.value.params["reason"] == "not_configured"
    p = Prometheus(MonitoringConfig(prometheus_url="http://prom:9090", prometheus_token="tok"))
    seen = {}

    def fake_get(url, params=None, headers=None, **kw):
        seen["headers"] = headers
        if url.endswith("/query_range"):
            return httpx.Response(200, json={"status": "success", "data": {"result": [
                {"metric": {"instance": "a"}, "values": [[1, "0.5"], [2, "0.7"]]}]}})
        return httpx.Response(200, json={"status": "success", "data": {"result": [{"metric": {}, "value": [1, "3"]}]}})

    monkeypatch.setattr("pkm.monitoring.httpx.get", fake_get)
    assert p.query("cluster_cpu") == [{"labels": {}, "value": 3.0}]
    assert seen["headers"] == {"Authorization": "Bearer tok"}
    assert p.query_range("node_cpu", "1h")[0]["values"] == [[1.0, 0.5], [2.0, 0.7]]
    assert p.ping()["targets"] == 1
    with pytest.raises(BadRequest):
        p.query("drop_everything")
    with pytest.raises(BadRequest):
        p.query_range("node_cpu", "1y")
    with pytest.raises(BadRequest):
        p.query_range("nope", "1h")
    monkeypatch.setattr("pkm.monitoring.httpx.get", lambda *a, **k: httpx.Response(500, text="err"))
    with pytest.raises(MetricsUnavailable):
        p.query("cluster_cpu")
    monkeypatch.setattr("pkm.monitoring.httpx.get",
                        lambda *a, **k: httpx.Response(200, json={"status": "error", "error": "bad"}))
    with pytest.raises(MetricsUnavailable):
        p.query("cluster_cpu")

    def down(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("pkm.monitoring.httpx.get", down)
    with pytest.raises(MetricsUnavailable) as e:
        p.ping()
    assert e.value.params["reason"] == "unreachable"


def test_monitoring_helpers(demo):
    from pkm.config import KubernetesConfig
    from pkm.k8s.service import KubernetesService
    from pkm.monitoring import node_usage, pod_usage, storage_overview

    k8s = KubernetesService(demo, KubernetesConfig())
    nu = node_usage(k8s)
    assert nu["metricsServer"] and len(nu["nodes"]) == 3
    assert next(n for n in nu["nodes"] if n["name"] == "node-03")["usageCpu"] is None
    pu = pod_usage(k8s, "production", sort="memory", limit=3)
    assert pu["metricsServer"] and len(pu["pods"]) == 3
    assert pu["pods"][0]["memory"] >= pu["pods"][1]["memory"]
    so = storage_overview(k8s, Prometheus(MonitoringConfig()))
    assert so["usageSource"] is None and {p["name"] for p in so["pvcs"]} >= {"uploads-staging", "data-redis-0"}
    k8s.close()
