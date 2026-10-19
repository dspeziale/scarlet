"""pkm-admin and pkm-server command line."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml

from pkm import cli
from pkm.config import AuthConfig
from pkm.db import Database
from pkm.security.users import UserService

PW = "Str0ng-Passw0rd!"


@pytest.fixture
def cfg(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "etc" / "config.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump({
        "database": {"path": str(tmp_path / "data" / "pkm.db")},
        "backup": {"directory": str(tmp_path / "data" / "backups")},
        "kubernetes": {"kubeconfig": str(tmp_path / "missing-kubeconfig")},
        "monitoring": {"prometheus_token": "very-secret"},
    }), encoding="utf-8")
    monkeypatch.setenv("PKM_CONFIG", str(path))
    return path


def run(capsys, *args, stdin: str | None = None, monkeypatch=None) -> tuple[int, str, str]:
    if stdin is not None:
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    code = 0
    try:
        cli.admin_main(list(args))
    except SystemExit as e:
        code = e.code or 0
    out = capsys.readouterr()
    return code, out.out, out.err


def test_check_config(cfg, capsys):
    code, out, err = run(capsys, "check-config")
    assert code == 0 and "very-secret" not in out and "********" in out
    assert "kubeconfig not found" in err and "warnings" in out


def test_invalid_config(tmp_path, capsys, monkeypatch):
    bad = tmp_path / "bad.yaml"
    bad.write_text("server:\n  port: 0\n", encoding="utf-8")
    code, _, err = run(capsys, "--config", str(bad), "check-config")
    assert code == 2 and "server.port" in err


def test_users_commands(cfg, capsys, monkeypatch):
    code, out, _ = run(capsys, "setup-token")
    assert code == 0 and len(out.strip()) > 10
    code, out, _ = run(capsys, "create-admin", "--username", "root", "--password-stdin", stdin=PW + "\n", monkeypatch=monkeypatch)
    assert code == 0 and "created" in out
    code, _, err = run(capsys, "create-admin", "--username", "weak", "--password-stdin", stdin="short\n", monkeypatch=monkeypatch)
    assert code == 1 and "policy" in err
    code, _, err = run(capsys, "setup-token")
    assert code == 1 and "already completed" in err
    code, out, _ = run(capsys, "list-users")
    assert "root" in out and "admin" in out
    code, out, _ = run(capsys, "reset-password", "root", "--password-stdin", stdin="An0ther-Passw0rd!\n", monkeypatch=monkeypatch)
    assert code == 0 and "updated" in out
    code, _, err = run(capsys, "reset-password", "ghost", "--password-stdin", stdin=PW, monkeypatch=monkeypatch)
    assert code == 1
    code, _, err = run(capsys, "reset-password", "root", "--password-stdin", stdin="x\n", monkeypatch=monkeypatch)
    assert code == 1
    code, out, _ = run(capsys, "unlock", "root")
    assert "unlocked" in out
    assert run(capsys, "unlock", "ghost")[0] == 1
    code, out, _ = run(capsys, "migrate")
    assert "schema version 1" in out
    code, out, _ = run(capsys, "purge-audit")
    assert "deleted" in out
    import yaml as _y

    db = Database(_y.safe_load(cfg.read_text())["database"]["path"])
    users = UserService(db, AuthConfig())
    assert users.authenticate("root", "An0ther-Passw0rd!")[0] == "ok"
    from pkm.audit import AuditService

    actions = {e["action"] for e in AuditService(db).search()["items"]}
    assert {"user.create", "user.password_reset", "user.unlock"} <= actions
    assert all(e["username"].startswith("cli:") for e in AuditService(db).search()["items"])


def test_interactive_password(cfg, capsys, monkeypatch):
    answers = iter([PW, PW])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers))
    assert run(capsys, "create-admin", "--username", "inter")[0] == 0
    answers2 = iter([PW, "different"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(answers2))
    code, _, err = run(capsys, "create-admin", "--username", "inter2")
    assert code == 1 and "do not match" in err


def test_backup_verify_restore(cfg, capsys, monkeypatch, tmp_path):
    run(capsys, "create-admin", "--username", "root", "--password-stdin", stdin=PW + "\n", monkeypatch=monkeypatch)
    code, out, _ = run(capsys, "backup", "--scheduled")
    assert code == 0
    info = json.loads(out)
    assert info["includes"] == ["database", "config"] and "-scheduled" in info["file"]
    code, out, _ = run(capsys, "verify-backup", info["file"])
    assert code == 0 and json.loads(out)["ok"]
    # change state, then restore
    db_path = yaml.safe_load(cfg.read_text())["database"]["path"]
    UserService(Database(db_path), AuthConfig()).create("later", PW, "viewer")
    monkeypatch.setattr("builtins.input", lambda prompt="": "no")
    assert run(capsys, "restore", info["file"])[0] == 1
    code, out, _ = run(capsys, "restore", info["file"], "--yes", "--with-config")
    assert code == 0 and len(json.loads(out)["restored"]) == 2
    users = UserService(Database(db_path), AuthConfig())
    assert users.get_by_username("later") is None
    from pkm.audit import AuditService

    assert AuditService(Database(db_path)).search(action="backup.restore")["total"] == 1
    # corrupted archive: verification fails, restore refuses
    p = Path(info["file"])
    p.write_bytes(p.read_bytes()[:100])
    assert run(capsys, "verify-backup", str(p))[0] == 1
    code, _, err = run(capsys, "restore", str(p), "--yes")
    assert code == 1 and "verification failed" in err


def test_backup_with_manifests_failure_is_reported(cfg, capsys, monkeypatch):
    def boom(**kw):
        raise OSError("disk full")

    monkeypatch.setattr("pkm.backup.BackupService.create", lambda self, **kw: boom())
    code, _, err = run(capsys, "backup")
    assert code == 1 and "disk full" in err


def test_backup_include_manifests_demo(tmp_path, capsys, monkeypatch):
    path = tmp_path / "c.yaml"
    path.write_text(yaml.safe_dump({"mode": "demo", "environment": "development",
                                    "database": {"path": str(tmp_path / "d.db")},
                                    "backup": {"directory": str(tmp_path / "b")}}), encoding="utf-8")
    code, out, _ = run(capsys, "--config", str(path), "backup", "--include-manifests")
    assert code == 0 and "k8s_manifests" in json.loads(out)["includes"]


def test_server_main(cfg, monkeypatch):
    called = {}

    def fake_run(app, **kw):
        called.update(kw)
        called["app"] = app

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", fake_run)
    cli.server_main([])
    assert called["port"] == 8080 and called["host"] == "127.0.0.1" and called["ssl_certfile"] is None
    assert called["server_header"] is False and called["forwarded_allow_ips"] is None
    assert called["app"].title.endswith("API")
