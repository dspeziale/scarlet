from __future__ import annotations


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_ok_when_migrated(client):
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"]["ok"] is True
    assert body["checks"]["database"]["schema"] == body["checks"]["database"]["expected_schema"]


def test_ready_fails_when_schema_not_migrated(make_client, unmigrated_db_url):
    with make_client(unmigrated_db_url) as c:
        r = c.get("/ready")
    assert r.status_code == 503
    db = r.json()["checks"]["database"]
    assert db["reachable"] is True
    assert db["schema"] == "not-migrated"


def test_ready_fails_when_db_unreachable(make_client):
    with make_client("postgresql+psycopg://u:p@127.0.0.1:1/none?connect_timeout=1") as c:
        r = c.get("/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["database"]["reachable"] is False


def test_simulate_unhealthy_flag(make_client, db_url):
    with make_client(db_url, SCARLET_SIMULATE_UNHEALTHY="true") as c:
        assert c.get("/health").status_code == 503
        assert c.get("/ready").status_code == 503


def test_version_reports_build_metadata(client):
    body = client.get("/version").json()
    assert body["application"] == "scarlet"
    assert body["version"] == "9.9.9-test"
    assert body["commit"] == "abcdef123456"
    assert body["image"].endswith(":git-abcdef123456")


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Cache-Control"] == "no-store"
