"""Scenario end-to-end con Docker reale: deploy, idempotenza, status/logs/restart, upgrade,
rollback, deploy fallito (unhealthy, crash, immagine inesistente, porta occupata, registry
non disponibile, migrazione fallita), backup e restore, doctor."""

from __future__ import annotations

import socket
import time
import urllib.request

import pytest
from helpers import (
    APP_NAME,
    APP_PORT,
    REGISTRY_NAME,
    REPO,
    TAG_A,
    TAG_B,
    TAG_BAD,
    TAG_BROKEN,
    TAG_CRASH,
    sh,
)

pytestmark = pytest.mark.integration


def _http(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{APP_PORT}{path}", timeout=3) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""
    except OSError:
        return 0, ""


def test_full_lifecycle(appctl, app_dir, images):
    # 1. primo deploy
    out = appctl.ok("deploy", TAG_A)
    assert "HEALTHY" in out
    st = appctl.json("status")
    assert st["status"] == "RUNNING" and st["health"] == "HEALTHY" and st["ready"] is True
    assert st["version"] == "1.0.0-it" and st["commit"] == "aaaaaaaaaaaa"
    assert st["image"] == f"{REPO}:{TAG_A}" and st["container"] == f"{APP_NAME}-app"
    assert st["deployed_by"] == "integration-test"
    assert _http("/health")[0] == 200 and _http("/ready")[0] == 200
    assert (app_dir / "current").resolve() == (app_dir / "releases" / TAG_A).resolve()

    # output testuale per l'operatore
    text = appctl.ok("status")
    assert "Application:" in text and "RUNNING" in text and "HEALTHY" in text

    # 2. idempotenza
    out = appctl.ok("deploy", TAG_A)
    assert "gia' in esecuzione" in out

    # 3. logs / version / health / history
    logs = appctl.ok("logs", "--tail", "50")
    assert "Uvicorn running" in logs or "Application startup" in logs
    ver = appctl.json("version")
    assert ver["running"]["commit"] == "aaaaaaaaaaaa"
    assert appctl.run("health").returncode == 0
    hist = appctl.json("history")
    assert [h["result"] for h in hist] == ["started", "success"]

    # 4. restart
    out = appctl.ok("restart")
    assert "HEALTHY" in out
    assert _http("/ready")[0] == 200

    # 5. stop / start
    appctl.ok("stop")
    assert _http("/health")[0] == 0
    assert appctl.json("status")["status"] == "STOPPED"
    appctl.ok("start")
    assert _http("/ready")[0] == 200

    # 6. upgrade alla versione B (con backup pre-migrazione)
    appctl.ok("deploy", TAG_B)
    st = appctl.json("status")
    assert st["version"] == "1.1.0-it" and st["previous"] == TAG_A
    assert list((app_dir / "backups").glob("db-*.sql.gz"))
    # i dati sopravvivono all'upgrade (stesso volume)
    code, body = _http("/version")
    assert code == 200 and "bbbbbbbbbbbb" in body

    # 7. rollback alla precedente
    out = appctl.ok("rollback")
    assert "HEALTHY" in out
    st = appctl.json("status")
    assert st["version"] == "1.0.0-it" and st["tag"] == TAG_A and st["previous"] == TAG_B
    assert "aaaaaaaaaaaa" in _http("/version")[1]

    # 8. audit log completo
    audit = (app_dir / "audit.log").read_text()
    for action in ("deploy", "restart", "stop", "start", "rollback", "backup"):
        assert f"action={action}" in audit, action
    assert "user=integration-test env=development" in audit

    # 9. backup e restore
    out = appctl.ok("backup")
    assert "Backup creato" in out
    dump = sorted((app_dir / "backups").glob("db-*.sql.gz"))[-1]
    assert appctl.run("restore", dump.name).returncode == 2  # richiede --yes
    appctl.ok("restore", dump.name, "--yes")
    assert _http("/ready")[0] == 200

    # 10. doctor
    r = appctl.run("doctor")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS] Docker Engine" in r.stdout and "[PASS] Health /health" in r.stdout
    assert "[FAIL]" not in r.stdout


def test_unhealthy_deploy_is_rolled_back(appctl, images):
    appctl.ok("deploy", TAG_A)
    r = appctl.run("deploy", TAG_BAD)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "FALLITO" in r.stderr and "Rollback riuscito" in r.stdout
    st = appctl.json("status")
    assert st["tag"] == TAG_A and st["health"] == "HEALTHY"
    assert "aaaaaaaaaaaa" in _http("/version")[1]
    hist = appctl.json("history")
    assert any(h["tag"] == TAG_BAD and h["result"] == "failed" for h in hist)
    assert any(h["action"] == "rollback" and h["result"] == "success" for h in hist)
    log = appctl.ok("logs", "--deploy")
    assert "DIAGNOSTICA" in log


def test_crashing_image_detected_quickly(appctl, images):
    appctl.ok("deploy", TAG_A)
    started = time.time()
    r = appctl.run("deploy", TAG_CRASH)
    assert r.returncode == 4, r.stdout + r.stderr
    assert time.time() - started < 90  # ben sotto HEALTH_TIMEOUT + rollback
    assert appctl.json("status")["tag"] == TAG_A
    failed = [
        h for h in appctl.json("history") if h["tag"] == TAG_CRASH and h["result"] == "failed"
    ]
    assert failed and ("terminato" in failed[0]["detail"] or "crash loop" in failed[0]["detail"])


def test_broken_image_fails_before_touching_running_version(appctl, images):
    appctl.ok("deploy", TAG_A)
    r = appctl.run("deploy", TAG_BROKEN)
    assert r.returncode == 8, r.stdout + r.stderr
    assert "migrazione database fallita" in r.stderr
    st = appctl.json("status")
    assert st["tag"] == TAG_A and st["health"] == "HEALTHY"
    assert "aaaaaaaaaaaa" in _http("/version")[1]


def test_missing_image(appctl, images):
    appctl.ok("deploy", TAG_A)
    r = appctl.run("deploy", "git-000000000000")
    assert r.returncode == 3
    assert "non disponibile nel registry" in r.stderr
    assert appctl.json("status")["tag"] == TAG_A and _http("/ready")[0] == 200


def test_registry_unavailable(appctl, images):
    appctl.ok("deploy", TAG_A)
    sh("docker", "stop", REGISTRY_NAME)
    try:
        r = appctl.run("deploy", TAG_B)
        assert r.returncode == 3, r.stdout + r.stderr
        assert "impossibile scaricare" in r.stderr
        assert _http("/ready")[0] == 200  # la versione corrente continua a funzionare
        # PULL_POLICY=missing consente il deploy di immagini gia' presenti localmente
        (appctl.app_dir / "app.conf").open("a").write("PULL_POLICY=missing\n")
        appctl.ok("deploy", TAG_A)
    finally:
        sh("docker", "start", REGISTRY_NAME)
        time.sleep(2)


def test_port_already_in_use(appctl, images):
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", APP_PORT))
    blocker.listen(1)
    try:
        r = appctl.run("deploy", TAG_A)
        assert r.returncode == 7, r.stdout + r.stderr
        assert (
            "port is already allocated" in r.stderr or "address already in use" in r.stderr.lower()
        )
        assert appctl.json("status")["status"] != "RUNNING"
    finally:
        blocker.close()
    # liberata la porta, il deploy riesce (idempotente rispetto allo stato inconsistente)
    appctl.ok("deploy", TAG_A)
    assert _http("/ready")[0] == 200


def test_migration_failure_keeps_old_version(appctl, images):
    appctl.ok("deploy", TAG_A)
    conf = appctl.app_dir / "app.conf"
    conf.write_text(
        conf.read_text().replace("alembic upgrade head", "alembic upgrade revisione-inesistente")
    )
    r = appctl.run("deploy", TAG_B)
    assert r.returncode == 8, r.stdout + r.stderr
    assert "migrazione database fallita" in r.stderr
    st = appctl.json("status")
    assert st["tag"] == TAG_A and st["health"] == "HEALTHY"
