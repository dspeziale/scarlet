"""Shared fixtures: a DEMO application with logged-in clients for each role."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pkm.config import Settings
from pkm.k8s.demo import DemoKubernetes
from pkm.main import create_app
from pkm.security.users import new_setup_token

PASSWORD = "Str0ng-Passw0rd!"
API = "/api/v1"


def make_settings(tmp_path: Path, **overrides) -> Settings:
    data = {
        "mode": "demo",
        "environment": "development",
        "database": {"path": str(tmp_path / "pkm.db")},
        "backup": {"directory": str(tmp_path / "backups")},
        "logging": {"level": "WARNING"},
    }
    data.update(overrides)
    return Settings(**data)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def app(settings: Settings):
    return create_app(settings, start_background=False)


@pytest.fixture
def ctx(app):
    return app.state.ctx


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    """Anonymous client; owns the application lifespan."""
    with TestClient(app) as c:
        yield c


def complete_setup(client: TestClient, ctx, username: str = "admin", password: str = PASSWORD) -> dict:
    token = new_setup_token(ctx.db)
    r = client.post(f"{API}/setup/complete", headers={"X-Setup-Token": token},
                    json={"admin": {"username": username, "password": password}})
    assert r.status_code == 200, r.text
    return r.json()


def login(app, username: str, password: str = PASSWORD) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    c.headers["X-CSRF-Token"] = r.json()["csrfToken"]
    return c


@pytest.fixture
def admin(app, client, ctx) -> TestClient:
    complete_setup(client, ctx)
    return login(app, "admin")


@pytest.fixture
def operator(app, admin, ctx) -> TestClient:
    ctx.users.create("oper", PASSWORD, "operator")
    return login(app, "oper")


@pytest.fixture
def viewer(app, admin, ctx) -> TestClient:
    ctx.users.create("view", PASSWORD, "viewer")
    return login(app, "view")


@pytest.fixture
def demo() -> DemoKubernetes:
    return DemoKubernetes()


def pod_name(client: TestClient, namespace: str, prefix: str) -> str:
    items = client.get(f"{API}/k8s/pods", params={"namespace": namespace}).json()["items"]
    return next(p["name"] for p in items if p["name"].startswith(prefix))
