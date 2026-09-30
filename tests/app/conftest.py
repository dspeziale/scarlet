"""Fixture comuni: database SQLite temporaneo migrato con Alembic (le migrazioni vere)."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]

API_TOKEN = "test-token-123"


def _run_alembic(db_url: str, *args: str) -> None:
    env = {**os.environ, "SCARLET_DATABASE_URL": db_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), *args],
        check=True,
        env=env,
        cwd=ROOT,
        capture_output=True,
    )


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'scarlet.db').as_posix()}"
    _run_alembic(url, "upgrade", "head")
    return url


@pytest.fixture
def unmigrated_db_url(tmp_path: Path) -> str:
    return f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"


def _make_client(monkeypatch: pytest.MonkeyPatch, db_url: str, **env: str) -> TestClient:
    from scarlet import config, db

    monkeypatch.setenv("SCARLET_DATABASE_URL", db_url)
    monkeypatch.setenv("SCARLET_API_TOKEN", API_TOKEN)
    monkeypatch.setenv("APP_VERSION", "9.9.9-test")
    monkeypatch.setenv("APP_COMMIT", "abcdef123456")
    monkeypatch.setenv("IMAGE", "ghcr.io/example/scarlet:git-abcdef123456")
    monkeypatch.delenv("SCARLET_SIMULATE_UNHEALTHY", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    config.reset_settings_cache()
    db.reset_engine_cache()

    from scarlet.main import app

    return TestClient(app)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, db_url: str) -> Iterator[TestClient]:
    with _make_client(monkeypatch, db_url) as c:
        yield c


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch):
    def factory(db_url: str, **env: str) -> TestClient:
        return _make_client(monkeypatch, db_url, **env)

    return factory
