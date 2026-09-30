"""Costanti e utilita' condivise dai test di integrazione (nessuna fixture)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APPCTL_DIR = ROOT / "platform" / "appctl"
REGISTRY_PORT = 5001
REGISTRY = f"127.0.0.1:{REGISTRY_PORT}"
REGISTRY_NAME = "appctl-it-registry"
REPO = f"{REGISTRY}/scarlet-it"
APP_NAME = "scarlet-it"
APP_PORT = 18080

TAG_A = "git-aaaaaaaaaaaa"
TAG_B = "git-bbbbbbbbbbbb"
TAG_BAD = "git-badbadbadbad"
TAG_CRASH = "git-crashcrashcr"
TAG_BROKEN = "git-brokenbroken"

ENABLED = os.environ.get("APPCTL_INTEGRATION") == "1" and sys.platform.startswith("linux")


def sh(*cmd: str, check: bool = True, timeout: int = 900, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd), check=check, timeout=timeout, capture_output=True, text=True, **kw
    )


def build_image(tag: str, version: str, base: str | None = None, extra: str = "") -> str:
    """Costruisce (e pubblica sul registry locale) un'immagine di test."""
    image = f"{REPO}:{tag}"
    if base is None:
        sh(
            "docker",
            "build",
            "-q",
            "--build-arg",
            f"APP_VERSION={version}",
            "--build-arg",
            f"APP_COMMIT={tag.removeprefix('git-')}",
            "--build-arg",
            "APP_BUILD_TIME=2026-09-30T00:00:00Z",
            "-t",
            image,
            str(ROOT),
        )
    else:
        dockerfile = f"FROM {base}\n{extra}\n"
        sh("docker", "build", "-q", "-t", image, "-f", "-", str(ROOT), input=dockerfile)
    sh("docker", "push", "-q", image)
    return image


class Appctl:
    """Esegue appctl come processo separato (come farebbe un operatore)."""

    def __init__(self, app_dir: Path):
        self.app_dir = app_dir

    def run(
        self, *args: str, actor: str = "integration-test", timeout: int = 600
    ) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONPATH": str(APPCTL_DIR), "APPCTL_ACTOR": actor}
        return subprocess.run(
            [sys.executable, "-m", "appctl", "--app-dir", str(self.app_dir), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def ok(self, *args: str) -> str:
        r = self.run(*args)
        assert r.returncode == 0, (
            f"appctl {' '.join(args)} -> {r.returncode}\n{r.stdout}\n{r.stderr}"
        )
        return r.stdout

    def json(self, *args: str) -> dict | list:
        return json.loads(self.ok("--json", *args))
