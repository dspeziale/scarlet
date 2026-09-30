from __future__ import annotations

import pytest
from fakes import BAD, REPO, A, B

from appctl import ops
from appctl.errors import EXIT_OK, EXIT_UNHEALTHY, AppctlError


def test_rollback_to_previous(ctx, capsys):
    ops.deploy(ctx, A)
    ops.deploy(ctx, B)
    runs_before = sum(1 for c in ctx.docker.calls if c[0] == "run")
    assert ops.rollback(ctx) == EXIT_OK
    assert ctx.state.current().tag == A
    assert ctx.state.previous().tag == B  # si puo' "tornare avanti"
    assert ctx.docker.containers["scarlet-app"]["Config"]["Image"] == f"{REPO}:{A}"
    # il rollback non esegue migrazioni
    assert sum(1 for c in ctx.docker.calls if c[0] == "run") == runs_before
    assert "schema del database NON" in capsys.readouterr().out
    assert [h for h in ctx.state.history() if h.action == "rollback" and h.result == "success"]


def test_rollback_to_explicit_tag_not_local(ctx):
    ops.deploy(ctx, A)
    # B non e' mai stata estratta localmente: viene recuperata dal registry
    assert ops.rollback(ctx, B) == EXIT_OK
    assert ctx.state.current().tag == B
    assert ("pull", f"{REPO}:{B}") in ctx.docker.calls


def test_rollback_without_previous(ctx):
    ops.deploy(ctx, A)
    with pytest.raises(AppctlError) as exc:
        ops.rollback(ctx)
    assert "nessuna versione precedente" in exc.value.message


def test_rollback_to_current_is_noop(ctx, capsys):
    ops.deploy(ctx, A)
    assert ops.rollback(ctx, A) == EXIT_OK
    assert "gia' quella in esecuzione" in capsys.readouterr().out


def test_rollback_to_unhealthy_version_does_not_pingpong(ctx):
    ops.deploy(ctx, A)
    ops.deploy(ctx, B)
    code = ops.rollback(ctx, BAD)
    assert code != EXIT_OK
    assert ctx.state.current().tag == B
    assert not [h for h in ctx.state.history() if h.action == "rollback" and h.tag == B]


def test_stop_start_restart(ctx, capsys):
    ops.deploy(ctx, A)
    assert ops.stop(ctx) == EXIT_OK
    assert ctx.docker.containers["scarlet-app"]["State"]["Status"] == "exited"
    assert ops.status(ctx) == EXIT_OK
    assert "STOPPED" in capsys.readouterr().out
    assert ops.start(ctx) == EXIT_OK
    assert ctx.docker.containers["scarlet-app"]["State"]["Status"] == "running"
    assert ops.restart(ctx) == EXIT_OK
    assert ("restart",) in ctx.docker.calls
    assert ops.restart(ctx, recreate=True) == EXIT_OK
    audit = ctx.cfg.audit_log.read_text()
    for action in ("stop", "start", "restart"):
        assert f"action={action}" in audit


def test_start_without_deployment(ctx):
    with pytest.raises(AppctlError) as exc:
        ops.start(ctx)
    assert "nessun deployment" in exc.value.message


def test_status_output(ctx, capsys):
    ops.deploy(ctx, A)
    capsys.readouterr()
    ops.status(ctx)
    out = capsys.readouterr().out
    assert "Application: scarlet" in out.replace("  ", " ")
    assert "Environment:" in out and "production" in out
    assert "Version:" in out and "1.0.0" in out
    assert f"{REPO}:{A}" in out
    assert "Status:" in out and "RUNNING" in out
    assert "Health:" in out and "HEALTHY" in out
    assert "Started:" in out and "2026-09-30" in out
    assert "Container:" in out and "scarlet-app" in out
    assert "Deployed by:" in out and "tester" in out


def test_status_not_deployed(ctx, capsys):
    ops.status(ctx)
    out = capsys.readouterr().out
    assert "NOT DEPLOYED" in out


def test_health_exit_codes(ctx, capsys):
    assert ops.health(ctx) == EXIT_UNHEALTHY
    ops.deploy(ctx, A)
    capsys.readouterr()
    assert ops.health(ctx) == EXIT_OK
    out = capsys.readouterr().out
    assert "Dependency database" in out and "Overall" in out and "HEALTHY" in out


def test_health_json(ctx, capsys):
    ops.deploy(ctx, A)
    ctx.out.as_json = True
    capsys.readouterr()
    ops.health(ctx)
    import json

    data = json.loads(capsys.readouterr().out)
    assert data["healthy"] is True and data["ready"] is True


def test_version_and_history(ctx, capsys):
    ops.deploy(ctx, A)
    ops.deploy(ctx, B)
    capsys.readouterr()
    ops.version(ctx)
    out = capsys.readouterr().out
    assert "CURRENT DEPLOYMENT" in out
    assert "1.1.0" in out and "bbbbbbbbbbbb" in out and f"1.0.0 ({A})" in out
    ops.history(ctx)
    out = capsys.readouterr().out
    assert A in out and B in out and "success" in out


def test_logs_arguments(ctx):
    ops.deploy(ctx, A)
    ops.logs(ctx, follow=True, since="1h", tail=50)
    assert (
        "logs",
        ("--tail", "50", "--timestamps", "--follow", "--since", "1h", "app"),
    ) in ctx.docker.calls
    ops.logs(ctx, all_services=True, tail=10)
    assert ("logs", ("--tail", "10", "--timestamps")) in ctx.docker.calls


def test_logs_deploy_and_audit(ctx, capsys):
    ops.deploy(ctx, A)
    capsys.readouterr()
    ops.logs(ctx, deploy_log=True)
    assert "# deploy git-aaaaaaaaaaaa da tester" in capsys.readouterr().out
    ops.logs(ctx, audit_log=True)
    assert "action=deploy" in capsys.readouterr().out


def test_backup_and_restore(ctx, capsys, tmp_path):
    ops.deploy(ctx, A)
    assert ops.backup(ctx) == EXIT_OK
    dumps = list(ctx.cfg.backups_dir.glob("db-*.sql.gz"))
    tars = list(ctx.cfg.backups_dir.glob("config-*.tar.gz"))
    assert len(dumps) == 1 and len(tars) == 1
    import gzip

    with gzip.open(dumps[0], "rt") as fh:
        assert "CREATE TABLE" in fh.read()
    # restore richiede conferma
    with pytest.raises(AppctlError):
        ops.restore(ctx, dumps[0].name)
    assert ops.restore(ctx, dumps[0].name, confirmed=True) == EXIT_OK
    assert any(c[0] == "exec" and c[2][0] == "psql" for c in ctx.docker.calls)
    assert "action=restore" in ctx.cfg.audit_log.read_text()


def test_backup_retention(ctx):
    import os
    import time

    ops.deploy(ctx, A)
    ctx.cfg.backups_dir.mkdir(exist_ok=True)
    old = ctx.cfg.backups_dir / "db-20200101-000000.sql.gz"
    old.write_bytes(b"x")
    past = time.time() - 30 * 86400
    os.utime(old, (past, past))
    ops.backup(ctx)
    assert not old.exists()


def test_doctor_reports(ctx, capsys):
    ops.deploy(ctx, A)
    capsys.readouterr()
    code = ops.doctor(ctx)
    out = capsys.readouterr().out
    assert "[PASS] Docker Engine" in out
    assert "Registry" in out and "401" in out
    assert "Health /health" in out
    assert "Esito:" in out
    assert code in (0, 1)


def test_doctor_detects_unhealthy_and_missing_release(ctx, capsys):
    ops.deploy(ctx, A)
    import shutil

    shutil.rmtree(ctx.cfg.release_dir(A))
    capsys.readouterr()
    code = ops.doctor(ctx)
    out = capsys.readouterr().out
    assert code == 1
    assert "[FAIL] Release corrente" in out
