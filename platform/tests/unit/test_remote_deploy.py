"""Test degli script shell della piattaforma: SSH non raggiungibile e gate SSH."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
REMOTE_DEPLOY = ROOT / "platform" / "ci" / "remote-deploy.sh"
GATE = ROOT / "platform" / "server" / "bin" / "appctl-ssh-gate"

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash non disponibile")

# Chiave finta, composta a runtime per non assomigliare a una chiave vera (secret scanning).
_MARK = "OPENSSH PRIVATE KEY"
FAKE_KEY = f"-----BEGIN {_MARK}-----\nAAAA\n-----END {_MARK}-----"


def _bash(script: Path, env: dict[str, str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(script)],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@pytest.mark.skipif(shutil.which("ssh") is None, reason="ssh non disponibile")
def test_ssh_unreachable_gives_exit_20():
    r = _bash(
        REMOTE_DEPLOY,
        {
            "DEPLOY_HOST": "127.0.0.1",
            "DEPLOY_PORT": "1",  # nessun sshd in ascolto
            "DEPLOY_SSH_KEY": FAKE_KEY,
            "DEPLOY_SSH_HOST_KEY": "[127.0.0.1]:1 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "ACTION": "deploy",
            "IMAGE_TAG": "git-aaaaaaaaaaaa",
            "SSH_CONNECT_TIMEOUT": "3",
        },
    )
    assert r.returncode == 20, r.stdout + r.stderr
    assert "SSH verso 127.0.0.1 fallito" in r.stdout
    assert "AAAA" not in r.stdout  # la chiave non finisce mai nei log


def test_remote_deploy_rejects_bad_inputs():
    base = {
        "DEPLOY_HOST": "h",
        "DEPLOY_SSH_KEY": FAKE_KEY,
        "DEPLOY_SSH_HOST_KEY": "h ssh-ed25519 AAAA",
        "ACTION": "deploy",
        "IMAGE_TAG": "git-aaaaaaaaaaaa",
    }
    r = _bash(REMOTE_DEPLOY, {**base, "ACTION": "destroy"})
    assert r.returncode == 21
    r = _bash(REMOTE_DEPLOY, {**base, "IMAGE_TAG": "bad tag; rm -rf /"})
    assert r.returncode == 21
    r = _bash(REMOTE_DEPLOY, {k: v for k, v in base.items() if k != "DEPLOY_HOST"})
    assert r.returncode != 0


@pytest.fixture
def fake_appctl(tmp_path: Path) -> Path:
    fake = tmp_path / "appctl"
    fake.write_text('#!/usr/bin/env bash\nprintf "ARGS:%s\\n" "$*"\n')
    fake.chmod(0o755)
    return fake


@pytest.mark.parametrize(
    "command,expected",
    [
        (
            "appctl --app scarlet --actor github-actions:mario deploy git-aaaaaaaaaaaa",
            "--app scarlet --actor github-actions:mario deploy git-aaaaaaaaaaaa",
        ),
        ("appctl --app scarlet rollback", "--app scarlet rollback"),
        ("appctl --app scarlet rollback v1.2.3", "--app scarlet rollback v1.2.3"),
        ("appctl --app scarlet --json version", "--app scarlet --json version"),
        ("appctl --app scarlet health --wait 30", "--app scarlet health --wait 30"),
        ("appctl status", "status"),
        ("appctl --app scarlet --version", "--app scarlet --version"),
    ],
)
def test_gate_allows_whitelisted_commands(fake_appctl: Path, command: str, expected: str):
    r = _bash(
        GATE,
        {
            "SSH_ORIGINAL_COMMAND": command,
            "APPCTL_BIN": str(fake_appctl),
            "PATH": os.environ["PATH"],
        },
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"ARGS:{expected}"


@pytest.mark.parametrize(
    "command",
    [
        "",
        "bash",
        "appctl stop",
        "appctl restore x --yes",
        "appctl --app-dir /etc status",
        "appctl deploy 'git-a'; rm -rf /",
        "appctl deploy git-a && cat /etc/passwd",
        "appctl --app Scarlet status",
        "appctl deploy",
        "appctl health --wait abc",
        "appctl status extra",
        "docker ps",
    ],
)
def test_gate_denies_everything_else(fake_appctl: Path, command: str):
    r = _bash(
        GATE,
        {
            "SSH_ORIGINAL_COMMAND": command,
            "APPCTL_BIN": str(fake_appctl),
            "PATH": os.environ["PATH"],
        },
    )
    assert r.returncode == 126, f"{command!r} doveva essere rifiutato: {r.stdout}"
    assert "non consentito" in r.stderr
