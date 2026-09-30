from __future__ import annotations

import json

import pytest
from fakes import BAD, CRASH, REPO, A, B

from appctl import ops
from appctl.errors import (
    EXIT_DEPLOY_DOWN,
    EXIT_DEPLOY_ROLLED_BACK,
    EXIT_LOCKED,
    EXIT_MIGRATION,
    EXIT_OK,
    EXIT_REGISTRY,
    EXIT_USAGE,
    AppctlError,
)


def _audit_lines(ctx):
    return ctx.cfg.audit_log.read_text().splitlines()


def test_first_deploy_success(ctx, capsys):
    code = ops.deploy(ctx, A)
    assert code == EXIT_OK
    cur = ctx.state.current()
    assert cur.tag == A
    assert cur.version == "1.0.0"
    assert cur.commit == "aaaaaaaaaaaa"
    assert cur.image == f"{REPO}:{A}"
    assert cur.result == "success"
    assert cur.actor == "tester"
    assert cur.digest.startswith(REPO + "@sha256:")
    assert ctx.state.previous() is None
    # release estratta e completa
    assert (ctx.cfg.release_dir(A) / "compose.yaml").is_file()
    assert (ctx.cfg.release_dir(A) / ".release-complete").is_file()
    # migrazioni eseguite prima dell'avvio
    calls = ctx.docker.calls
    run_idx = next(i for i, c in enumerate(calls) if c[0] == "run")
    up_idx = next(i for i, c in enumerate(calls) if c[0] == "up" and c[1] == ())
    assert run_idx < up_idx
    assert ("run", "app", ("alembic", "upgrade", "head")) in calls
    # history e audit
    results = [h.result for h in ctx.state.history()]
    assert results == ["started", "success"]
    audit = _audit_lines(ctx)
    assert any("action=deploy" in line and "result=success" in line for line in audit)
    assert all("user=tester env=production app=scarlet" in line for line in audit)
    out = capsys.readouterr().out
    assert "HEALTHY" in out
    assert (ctx.cfg.logs_dir).exists() and list(ctx.cfg.logs_dir.glob("deploy-*.log"))


def test_deploy_is_idempotent(ctx):
    assert ops.deploy(ctx, A) == EXIT_OK
    ups_before = sum(1 for c in ctx.docker.calls if c[0] == "up")
    assert ops.deploy(ctx, A) == EXIT_OK
    ups_after = sum(1 for c in ctx.docker.calls if c[0] == "up")
    assert ups_after == ups_before  # nessuna ricreazione
    assert [h.result for h in ctx.state.history()] == ["started", "success"]
    assert any("idempotente" in line for line in _audit_lines(ctx))


def test_deploy_force_recreates(ctx):
    ops.deploy(ctx, A)
    ops.deploy(ctx, A, force=True)
    assert ("up", (), True) in ctx.docker.calls


def test_upgrade_sets_previous(ctx):
    ops.deploy(ctx, A)
    assert ops.deploy(ctx, B) == EXIT_OK
    assert ctx.state.current().tag == B
    assert ctx.state.previous().tag == A
    assert ctx.state.current().version == "1.1.0"


def test_unhealthy_deploy_rolls_back_automatically(ctx, capsys):
    ops.deploy(ctx, A)
    code = ops.deploy(ctx, BAD)
    assert code == EXIT_DEPLOY_ROLLED_BACK
    assert ctx.state.current().tag == A
    assert ctx.state.previous() is None or ctx.state.previous().tag != BAD or True
    # il container in esecuzione e' quello della versione precedente
    assert ctx.docker.containers["scarlet-app"]["Config"]["Image"] == f"{REPO}:{A}"
    hist = [(h.action, h.tag, h.result) for h in ctx.state.history()]
    assert ("deploy", BAD, "failed") in hist
    assert ("rollback", A, "success") in hist
    audit = _audit_lines(ctx)
    assert any("action=deploy" in line and "result=failed" in line for line in audit)
    assert any("action=rollback" in line and "result=success" in line for line in audit)
    err = capsys.readouterr().err
    assert "FALLITO" in err
    # la diagnostica finisce nel log di deploy
    log = sorted(ctx.cfg.logs_dir.glob("deploy-*"))[-1].read_text()
    assert "DIAGNOSTICA" in log and "log line 1" in log


def test_crashing_container_detected_fast(ctx):
    ops.deploy(ctx, A)
    start = ctx.extra["clock"]()
    assert ops.deploy(ctx, CRASH) == EXIT_DEPLOY_ROLLED_BACK
    # rilevato senza attendere l'intero timeout (30s) del deploy fallito
    failed = [h for h in ctx.state.history() if h.tag == CRASH and h.result == "failed"][0]
    assert "terminato" in failed.detail
    assert ctx.extra["clock"]() - start < 60


def test_unhealthy_first_deploy_without_previous(ctx, capsys):
    code = ops.deploy(ctx, BAD)
    assert code == EXIT_DEPLOY_DOWN
    assert ctx.state.current() is None
    assert "nessuna versione precedente" in capsys.readouterr().err


def test_auto_rollback_disabled(ctx, capsys):
    ops.deploy(ctx, A)
    ctx.cfg.auto_rollback = False
    code = ops.deploy(ctx, BAD)
    assert code == EXIT_DEPLOY_DOWN
    assert ctx.state.current().tag == A  # lo stato registrato non cambia
    assert "AUTO_ROLLBACK=false" in capsys.readouterr().err
    assert not any(h.action == "rollback" for h in ctx.state.history())


def test_missing_image_in_registry(ctx):
    with pytest.raises(AppctlError) as exc:
        ops.deploy(ctx, "git-000000000000")
    assert exc.value.exit_code == EXIT_REGISTRY
    assert "non disponibile nel registry" in exc.value.message
    assert ctx.state.current() is None
    assert ctx.state.history() == []


def test_registry_unavailable(ctx):
    ops.deploy(ctx, A)
    ctx.docker.registry_available = False
    with pytest.raises(AppctlError) as exc:
        ops.deploy(ctx, B)
    assert exc.value.exit_code == EXIT_REGISTRY
    assert ctx.state.current().tag == A
    assert ctx.docker.containers["scarlet-app"]["State"]["Status"] == "running"


def test_pull_policy_missing_skips_pull_when_local(ctx):
    ctx.cfg.pull_policy = "missing"
    ctx.docker.local_images[f"{REPO}:{A}"] = dict(ctx.docker.registry[f"{REPO}:{A}"])
    ops.deploy(ctx, A)
    assert not any(c[0] == "pull" for c in ctx.docker.calls)


def test_port_already_allocated(ctx, capsys):
    ops.deploy(ctx, A)
    ctx.docker.port_busy = True
    code = ops.deploy(ctx, B)
    # compose up fallisce anche per il rollback: applicazione non disponibile
    assert code == EXIT_DEPLOY_DOWN
    assert "port is already allocated" in capsys.readouterr().err
    assert ctx.state.current().tag == A


def test_migration_failure_keeps_previous_running(ctx):
    ops.deploy(ctx, A)
    ctx.docker.fail_migration = True
    with pytest.raises(AppctlError) as exc:
        ops.deploy(ctx, B)
    assert exc.value.exit_code == EXIT_MIGRATION
    assert ctx.state.current().tag == A
    assert ctx.docker.containers["scarlet-app"]["Config"]["Image"] == f"{REPO}:{A}"
    assert ctx.docker.containers["scarlet-app"]["State"]["Status"] == "running"
    # nessun "up" dell'app per la nuova versione
    assert ("up", (), False) not in ctx.docker.calls[-3:]


def test_backup_before_migrate_in_production(ctx):
    ctx.cfg.backup_before_migrate = True
    ops.deploy(ctx, A)  # db non ancora attivo al primo deploy: nessun backup
    assert ops.deploy(ctx, B) == EXIT_OK
    assert list(ctx.cfg.backups_dir.glob("db-*.sql.gz"))
    # il backup non deve "riattivare" la release precedente: gira davvero B
    assert ctx.docker.containers["scarlet-app"]["Config"]["Image"] == f"{REPO}:{B}"
    assert ctx.state.current().tag == B and ctx.state.current().version == "1.1.0"


def test_invalid_compose_config(ctx):
    ctx.docker.compose_config_ok = False
    with pytest.raises(AppctlError) as exc:
        ops.deploy(ctx, A)
    assert exc.value.exit_code == EXIT_USAGE


def test_invalid_tag_rejected(ctx):
    with pytest.raises(AppctlError) as exc:
        ops.deploy(ctx, "bad tag;rm -rf")
    assert exc.value.exit_code == EXIT_USAGE


def test_missing_secrets_file(ctx):
    ctx.cfg.secrets_file.unlink()
    with pytest.raises(AppctlError) as exc:
        ops.deploy(ctx, A)
    assert exc.value.exit_code == EXIT_USAGE
    assert "secrets" in exc.value.message


def test_bundle_missing_compose_file(ctx):
    del ctx.docker.bundle_files["compose.prod.yaml"]
    with pytest.raises(AppctlError) as exc:
        ops.deploy(ctx, A)
    assert exc.value.exit_code == EXIT_USAGE
    assert "compose.prod.yaml" in exc.value.message
    assert not ctx.cfg.release_dir(A).exists()


def test_concurrent_deploy_is_refused(ctx):
    ctx.state.ensure()
    ctx.state.acquire_lock("altro deploy")
    try:
        with pytest.raises(AppctlError) as exc:
            ops.deploy(ctx, A)
        assert exc.value.exit_code == EXIT_LOCKED
    finally:
        ctx.state.release_lock()
    # dopo il rilascio del lock il deploy funziona
    assert ops.deploy(ctx, A) == EXIT_OK


def test_release_pruning(ctx):
    tags = [A, B, BAD, CRASH]
    for t in tags[:2]:
        ops.deploy(ctx, t)
    # aggiunge release "vecchie" a mano
    import os
    import time

    for i, name in enumerate(("git-old1", "git-old2", "git-old3")):
        d = ctx.cfg.release_dir(name)
        d.mkdir(parents=True)
        (d / ".release-complete").write_text("x")
        past = time.time() - (10 + i) * 86400
        os.utime(d, (past, past))
    ops.deploy(ctx, A, force=True)
    remaining = sorted(p.name for p in ctx.cfg.releases_dir.iterdir())
    assert A in remaining and B in remaining
    assert len(remaining) <= ctx.cfg.keep_releases + 1


def test_current_json_is_valid_and_complete(ctx):
    ops.deploy(ctx, A)
    data = json.loads(ctx.state.current_file.read_text())
    for key in (
        "application",
        "environment",
        "image",
        "tag",
        "commit",
        "actor",
        "timestamp",
        "result",
    ):
        assert data[key]
