from __future__ import annotations

from tests.app.conftest import API_TOKEN

HEADERS = {"X-API-Key": API_TOKEN}


def _payload(**overrides):
    base = {
        "application": "scarlet",
        "environment": "development",
        "version": "0.1.0",
        "image": "ghcr.io/example/scarlet:git-abcdef123456",
        "commit": "abcdef123456",
        "actor": "github-actions:mario",
        "repository": "https://github.com/example/scarlet",
    }
    return {**base, **overrides}


def test_post_requires_api_key(client):
    assert client.post("/api/deployments", json=_payload()).status_code == 401
    r = client.post("/api/deployments", json=_payload(), headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_post_refused_when_token_not_configured(make_client, db_url):
    with make_client(db_url, SCARLET_API_TOKEN="") as c:
        r = c.post("/api/deployments", json=_payload(), headers=HEADERS)
    assert r.status_code == 503


def test_record_and_list_deployments(client):
    r = client.post("/api/deployments", json=_payload(), headers=HEADERS)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["application"] == "scarlet"
    assert body["result"] == "success"

    r = client.post(
        "/api/deployments",
        json=_payload(version="0.1.1", environment="production"),
        headers=HEADERS,
    )
    assert r.status_code == 201

    r = client.get("/api/deployments")
    assert r.status_code == 200
    assert [d["version"] for d in r.json()] == ["0.1.1", "0.1.0"]

    r = client.get("/api/deployments", params={"environment": "production"})
    assert [d["version"] for d in r.json()] == ["0.1.1"]

    r = client.get("/api/applications")
    apps = r.json()
    assert len(apps) == 1
    assert apps[0]["current"]["development"]["version"] == "0.1.0"
    assert apps[0]["current"]["production"]["version"] == "0.1.1"


def test_failed_deployment_does_not_become_current(client):
    client.post("/api/deployments", json=_payload(version="1.0.0"), headers=HEADERS)
    client.post(
        "/api/deployments", json=_payload(version="1.0.1", result="failed"), headers=HEADERS
    )
    apps = client.get("/api/applications").json()
    assert apps[0]["current"]["development"]["version"] == "1.0.0"


def test_validation_rejects_bad_names(client):
    r = client.post("/api/deployments", json=_payload(application="Bad Name!"), headers=HEADERS)
    assert r.status_code == 422
    r = client.post("/api/deployments", json=_payload(environment="staging"), headers=HEADERS)
    assert r.status_code == 422


def test_index_page_lists_deployments_escaped(client):
    client.post("/api/deployments", json=_payload(actor="<script>x</script>"), headers=HEADERS)
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<script>x</script>" not in r.text
    assert "&lt;script&gt;" in r.text
    assert "9.9.9-test" in r.text


def test_index_page_empty(client):
    assert "Nessun deployment" in client.get("/").text
