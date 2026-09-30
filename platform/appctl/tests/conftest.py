"""Fixture per i test di appctl: Docker e HTTP finti, directory applicativa temporanea."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # pacchetto appctl
sys.path.insert(0, str(HERE))  # fakes.py

from fakes import REPO, FakeClock, FakeDocker, FakeHttp, write_app  # noqa: E402

from appctl.audit import AuditLog  # noqa: E402
from appctl.config import load_config  # noqa: E402
from appctl.ops import Context  # noqa: E402
from appctl.output import Printer  # noqa: E402
from appctl.state import StateStore  # noqa: E402


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    d = tmp_path / "apps" / "scarlet"
    write_app(d)
    return d


@pytest.fixture
def ctx(app_dir: Path, capsys) -> Context:
    cfg = load_config(app_dir)
    docker = FakeDocker(cfg.name, cfg.compose_env(image=""))
    docker.registry = {
        f"{REPO}:git-aaaaaaaaaaaa": {
            "health": "healthy",
            "version": "1.0.0",
            "commit": "aaaaaaaaaaaa",
        },
        f"{REPO}:git-bbbbbbbbbbbb": {
            "health": "healthy",
            "version": "1.1.0",
            "commit": "bbbbbbbbbbbb",
        },
        f"{REPO}:git-badbadbadbad": {
            "health": "unhealthy",
            "version": "1.2.0",
            "commit": "badbadbadbad",
        },
        f"{REPO}:git-crashcrashcr": {
            "health": "crash",
            "version": "1.3.0",
            "commit": "crashcrashcr",
        },
    }
    clock = FakeClock()
    c = Context(
        cfg=cfg,
        docker=docker,
        http=FakeHttp(docker),
        state=StateStore(cfg.state_dir),
        audit=AuditLog(cfg.audit_log, cfg.name, cfg.environment, "tester"),
        out=Printer(),
        actor="tester",
        sleep=clock.sleep,
        clock=clock,
    )
    c.extra["clock"] = clock
    return c
