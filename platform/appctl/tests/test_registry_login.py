from __future__ import annotations

import io

import pytest
from fakes import REPO, A, B

from appctl import cli, ops
from appctl.errors import EXIT_OK, EXIT_REGISTRY, EXIT_USAGE, AppctlError


def test_pull_with_temporary_login(ctx):
    ctx.extra["registry_login"] = ("github-actions", "good-token")
    assert ops.deploy(ctx, A) == EXIT_OK
    calls = ctx.docker.calls
    login = next(i for i, c in enumerate(calls) if c[0] == "login")
    pull = next(i for i, c in enumerate(calls) if c[0] == "pull")
    logout = next(i for i, c in enumerate(calls) if c[0] == "logout")
    assert login < pull < logout
    assert calls[login] == ("login", "registry.test", "github-actions")


def test_login_failure_is_registry_error(ctx):
    ctx.extra["registry_login"] = ("github-actions", "bad")
    with pytest.raises(AppctlError) as exc:
        ops.deploy(ctx, A)
    assert exc.value.exit_code == EXIT_REGISTRY
    assert "login al registry" in exc.value.message


def test_logout_even_when_pull_fails(ctx):
    ctx.extra["registry_login"] = ("u", "good-token")
    with pytest.raises(AppctlError):
        ops.deploy(ctx, "git-000000000000")
    assert ("logout", "registry.test") in ctx.docker.calls


def test_pull_failure_with_local_image_continues(ctx, capsys):
    ops.deploy(ctx, A)
    ops.deploy(ctx, B)
    ctx.docker.registry_available = False
    # A e' ancora presente localmente (release conservata): rollback possibile anche senza registry
    assert ops.rollback(ctx) == EXIT_OK
    assert "uso l'immagine gia' presente" in capsys.readouterr().err
    assert ctx.docker.containers["scarlet-app"]["Config"]["Image"] == f"{REPO}:{A}"


def test_cli_reads_login_from_stdin(app_dir, monkeypatch):
    monkeypatch.delenv("SUDO_USER", raising=False)
    parser = cli.build_parser()
    args = parser.parse_args(["--app-dir", str(app_dir), "deploy", A, "--registry-login-stdin"])
    ctx = cli.build_context(args)
    monkeypatch.setattr("sys.stdin", io.StringIO("github-actions:ghs_abc\n"))
    cli._read_registry_login(ctx)
    assert ctx.extra["registry_login"] == ("github-actions", "ghs_abc")
    monkeypatch.setattr("sys.stdin", io.StringIO("senza-due-punti\n"))
    with pytest.raises(AppctlError) as exc:
        cli._read_registry_login(ctx)
    assert exc.value.exit_code == EXIT_USAGE
