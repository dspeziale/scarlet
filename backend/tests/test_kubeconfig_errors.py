"""The kubeconfig problems are reported with a precise reason, not the client's generic message."""

from __future__ import annotations

from pathlib import Path

import pytest

from pkm.config import KubernetesConfig
from pkm.k8s.live import LiveKubernetes


def reason(path: str | None) -> str | None:
    info = LiveKubernetes(KubernetesConfig(kubeconfig=path)).info()
    assert info["connected"] is False
    return (info["error"]["params"] or {}).get("reason")


def test_missing_path() -> None:
    assert reason(None) == "no_kubeconfig"


def test_relative_path() -> None:
    assert reason("kubeconfig") == "path_not_absolute"


def test_file_not_found(tmp_path: Path) -> None:
    assert reason(str(tmp_path / "nope")) == "file_not_found"


def test_directory(tmp_path: Path) -> None:
    assert reason(str(tmp_path)) == "not_a_file"


def test_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "kc"
    f.write_text("", encoding="utf-8")
    assert reason(str(f)) == "empty_file"


def test_invalid_file(tmp_path: Path) -> None:
    f = tmp_path / "kc"
    f.write_text("hello: world\n", encoding="utf-8")
    assert reason(str(f)) == "invalid_file"


@pytest.mark.skipif(not hasattr(__import__("os"), "geteuid") or __import__("os").geteuid() == 0, reason="POSIX non-root only")
def test_not_readable(tmp_path: Path) -> None:
    f = tmp_path / "kc"
    f.write_text("apiVersion: v1\n", encoding="utf-8")
    f.chmod(0)
    assert reason(str(f)) == "not_readable"
