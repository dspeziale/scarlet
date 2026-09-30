"""Test di integrazione con PostgreSQL reale: migrazioni Alembic e readiness.

Eseguito solo se SCARLET_TEST_DATABASE_URL e' impostata (in CI punta al service container).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from tests.app.conftest import API_TOKEN, _run_alembic

PG_URL = os.environ.get("SCARLET_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not PG_URL, reason="SCARLET_TEST_DATABASE_URL non impostata")


@pytest.fixture
def pg_url() -> str:
    assert PG_URL
    engine = create_engine(PG_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    engine.dispose()
    return PG_URL


def test_migrations_upgrade_downgrade_upgrade(pg_url: str, make_client):
    _run_alembic(pg_url, "upgrade", "head")
    with make_client(pg_url) as c:
        assert c.get("/ready").status_code == 200
        r = c.post(
            "/api/deployments",
            json={
                "application": "scarlet",
                "environment": "production",
                "version": "1.0.0",
                "image": "ghcr.io/example/scarlet:git-abcdef123456",
                "actor": "test",
            },
            headers={"X-API-Key": API_TOKEN},
        )
        assert r.status_code == 201, r.text
        assert c.get("/api/applications").json()[0]["current"]["production"]["version"] == "1.0.0"
    _run_alembic(pg_url, "downgrade", "base")
    with make_client(pg_url) as c:
        assert c.get("/ready").status_code == 503
    _run_alembic(pg_url, "upgrade", "head")
    with make_client(pg_url) as c:
        assert c.get("/ready").status_code == 200
