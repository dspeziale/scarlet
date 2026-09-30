"""Operazioni applicative di appctl.

Ogni funzione riceve un ``Context`` (configurazione, client Docker, prober HTTP, stato, audit,
output) e restituisce l'exit code. Le funzioni non conoscono argparse: la CLI le richiama.
"""

from __future__ import annotations

import gzip
import os
import shlex
import shutil
import socket
import stat
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from appctl.audit import AuditLog
from appctl.config import AppConfig, parse_env_file, validate_tag
from appctl.errors import (
    EXIT_DEPLOY_DOWN,
    EXIT_DEPLOY_ROLLED_BACK,
    EXIT_FAILURE,
    EXIT_MIGRATION,
    EXIT_OK,
    EXIT_UNHEALTHY,
    EXIT_USAGE,
    AppctlError,
    RegistryError,
    UsageError,
)
from appctl.http import HttpProber
from appctl.output import Printer
from appctl.runner import DockerClient
from appctl.state import DeploymentRecord, StateStore, fmt_ts, now_iso


@dataclass
class Context:
    cfg: AppConfig
    docker: DockerClient
    http: HttpProber
    state: StateStore
    audit: AuditLog
    out: Printer
    actor: str
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    extra: dict = field(default_factory=dict)


# ============================================================================ helpers
@dataclass
class ContainerInfo:
    exists: bool = False
    status: str = "absent"  # running | exited | restarting | created | absent ...
    health: str = "none"  # healthy | unhealthy | starting | none
    started_at: str = ""
    finished_at: str = ""
    exit_code: int = 0
    restart_count: int = 0
    image: str = ""
    log_driver: str = ""
    log_opts: dict = field(default_factory=dict)

    @property
    def display_status(self) -> str:
        return {
            "running": "RUNNING",
            "exited": "STOPPED",
            "created": "CREATED",
            "restarting": "RESTARTING",
            "paused": "PAUSED",
            "dead": "DEAD",
            "absent": "NOT DEPLOYED",
        }.get(self.status, self.status.upper())

    @property
    def display_health(self) -> str:
        if self.status != "running":
            return "STOPPED" if self.exists else "-"
        return {"healthy": "HEALTHY", "unhealthy": "UNHEALTHY", "starting": "STARTING"}.get(
            self.health, "UNKNOWN"
        )


def container_info(ctx: Context, name: str | None = None) -> ContainerInfo:
    raw = ctx.docker.inspect_container(name or ctx.cfg.app_container)
    if not raw:
        return ContainerInfo()
    state = raw.get("State", {})
    health = (state.get("Health") or {}).get("Status", "none")
    host_cfg = raw.get("HostConfig", {})
    log_cfg = host_cfg.get("LogConfig", {}) or {}
    return ContainerInfo(
        exists=True,
        status=state.get("Status", "unknown"),
        health=health or "none",
        started_at=state.get("StartedAt", ""),
        finished_at=state.get("FinishedAt", ""),
        exit_code=int(state.get("ExitCode", 0) or 0),
        restart_count=int(raw.get("RestartCount", 0) or 0),
        image=(raw.get("Config", {}) or {}).get("Image", ""),
        log_driver=log_cfg.get("Type", ""),
        log_opts=log_cfg.get("Config", {}) or {},
    )


def _release_ready(cfg: AppConfig, tag: str) -> bool:
    d = cfg.release_dir(tag)
    return (d / ".release-complete").is_file() and all((d / f).is_file() for f in cfg.compose_files)


def activate_release(ctx: Context, tag: str) -> Path:
    """Punta docker compose alla release <tag> (deve essere gia' estratta)."""
    if not _release_ready(ctx.cfg, tag):
        raise AppctlError(
            f"release {tag} non presente in {ctx.cfg.releases_dir}",
            hint=f"eseguire: appctl deploy {tag}",
        )
    release_dir = ctx.cfg.release_dir(tag)
    ctx.docker.set_release(release_dir, ctx.cfg.compose_files, ctx.cfg.image_ref(tag))
    return release_dir


def require_current(ctx: Context) -> DeploymentRecord:
    cur = ctx.state.current()
    if cur is None:
        raise AppctlError(
            "nessun deployment registrato per questa applicazione",
            hint="eseguire il primo deploy con: appctl deploy <tag>",
        )
    activate_release(ctx, cur.tag)
    return cur


def _update_current_link(cfg: AppConfig, tag: str) -> None:
    link = cfg.current_link
    tmp = cfg.app_dir / ".current.tmp"
    try:
        if tmp.is_symlink() or tmp.exists():
            tmp.unlink()
        os.symlink(f"releases/{tag}", tmp)
        os.replace(tmp, link)
    except OSError:
        # Filesystem senza symlink (es. test su Windows): non e' bloccante.
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()


def fetch_version(ctx: Context) -> dict:
    probe = ctx.http.get(ctx.cfg.version_url)
    return probe.body or {}


def wait_healthy(ctx: Context, timeout: int | None = None) -> tuple[bool, str]:
    """Health gate: container running (+healthy se ha HEALTHCHECK) e /health + /ready OK."""
    cfg = ctx.cfg
    timeout = cfg.health_timeout if timeout is None else timeout
    deadline = ctx.clock() + timeout
    last = "in attesa"
    initial_restarts: int | None = None
    while True:
        info = container_info(ctx)
        if info.exists and info.status in ("exited", "dead"):
            return False, f"container terminato (exit code {info.exit_code})"
        if info.exists:
            if initial_restarts is None:
                initial_restarts = info.restart_count
            elif info.restart_count - initial_restarts >= 2:
                return False, f"container in crash loop ({info.restart_count} riavvii)"
        docker_ok = info.exists and info.status == "running" and info.health in ("healthy", "none")
        if docker_ok:
            h = ctx.http.get(cfg.health_url)
            r = ctx.http.get(cfg.ready_url)
            if h.ok and r.ok:
                return True, ""
            if not h.ok:
                last = f"/health -> {h.status or 'nessuna risposta'} {h.error or ''}".strip()
            else:
                reason = ""
                if r.body and isinstance(r.body.get("checks"), dict):
                    failing = [k for k, v in r.body["checks"].items() if not v.get("ok")]
                    if failing:
                        details = "; ".join(
                            f"{k}: {r.body['checks'][k].get('error', 'non ok')}" for k in failing
                        )
                        reason = f" ({details})"
                last = f"/ready -> {r.status or 'nessuna risposta'}{reason}"
        elif info.exists:
            last = f"container {info.status}, health docker {info.health}"
        else:
            last = "container non ancora creato"
        if ctx.clock() >= deadline:
            return False, f"timeout dopo {timeout}s: {last}"
        ctx.sleep(cfg.health_interval)


def _diagnostics(ctx: Context, lines: int = 40) -> str:
    info = container_info(ctx)
    parts = [
        f"container {ctx.cfg.app_container}: stato={info.status} health={info.health} "
        f"exit_code={info.exit_code} riavvii={info.restart_count}"
    ]
    if info.exists:
        parts.append(f"--- ultime {lines} righe di log ---")
        parts.append(ctx.docker.container_logs_tail(ctx.cfg.app_container, lines).rstrip())
    return "\n".join(parts)


def _ensure_dirs(cfg: AppConfig) -> None:
    for d in (cfg.releases_dir, cfg.state_dir, cfg.logs_dir):
        d.mkdir(parents=True, exist_ok=True)


def _check_config_files(cfg: AppConfig) -> None:
    if not cfg.app_env_file.is_file():
        raise UsageError(f"file di configurazione mancante: {cfg.app_env_file}")
    if not cfg.secrets_file.is_file():
        raise UsageError(
            f"file secrets mancante: {cfg.secrets_file}",
            "creare da deploy/secrets.env.example con permessi 0600",
        )


# ============================================================================ deploy
def pull_and_extract(ctx: Context, tag: str) -> str:
    """Scarica l'immagine (secondo PULL_POLICY) ed estrae il bundle. Ritorna l'image ref."""
    cfg = ctx.cfg
    image = cfg.image_ref(tag)
    if cfg.pull_policy == "always" or not ctx.docker.image_exists_locally(image):
        ctx.out.step(f"scarico immagine {image}")
        r = ctx.docker.pull(image)
        if not r.ok:
            err = (r.stderr or r.stdout).strip().splitlines()
            msg = err[-1] if err else "errore sconosciuto"
            if "not found" in msg or "manifest unknown" in msg or "denied" in msg:
                raise RegistryError(
                    f"immagine non disponibile nel registry: {image}",
                    hint="verificare il tag (appctl history, GitHub Actions) e le credenziali del registry (appctl doctor)",
                )
            raise RegistryError(
                f"impossibile scaricare {image}: {msg[:200]}",
                hint="registry non raggiungibile? verificare con: appctl doctor",
            )
    else:
        ctx.out.step(f"immagine {image} gia' presente")
    if not _release_ready(cfg, tag):
        ctx.out.step(f"estraggo il bundle di deploy in releases/{tag}")
        dest = cfg.release_dir(tag)
        ctx.docker.extract_bundle(image, dest)
        missing = [f for f in cfg.compose_files if not (dest / f).is_file()]
        if missing:
            shutil.rmtree(dest, ignore_errors=True)
            raise UsageError(
                f"il bundle dell'immagine non contiene: {', '.join(missing)}",
                "verificare COMPOSE_FILES in app.conf e la directory deploy/ del repository",
            )
        (dest / ".release-complete").write_text(now_iso() + "\n", encoding="utf-8")
    return image


def run_migrations(ctx: Context, tag: str) -> None:
    cfg = ctx.cfg
    if not cfg.migrate_command:
        return
    if cfg.db_service:
        ctx.out.step(f"avvio servizio {cfg.db_service}")
        r = ctx.docker.compose_up(cfg.db_service)
        if not r.ok:
            raise AppctlError(
                f"impossibile avviare il database: {r.stderr.strip()[:300]}", EXIT_MIGRATION
            )
        if cfg.backup_before_migrate:
            db_info = container_info(ctx, f"{cfg.name}-{cfg.db_service}")
            if db_info.status == "running":
                ctx.out.step("backup del database prima della migrazione")
                backup(ctx, quiet=True)
                # il backup opera sulla release corrente: si torna a quella da deployare
                activate_release(ctx, tag)
    ctx.out.step(f"eseguo migrazioni: {cfg.migrate_command}")
    r = ctx.docker.compose_run(cfg.app_service, shlex.split(cfg.migrate_command))
    if not r.ok:
        tail = (r.stderr or r.stdout).strip().splitlines()[-5:]
        raise AppctlError(
            "migrazione database fallita: " + " | ".join(tail)[:400],
            EXIT_MIGRATION,
            "la versione precedente e' ancora in esecuzione; vedere: appctl logs --deploy",
        )


def prune_releases(ctx: Context, keep_tags: set[str]) -> None:
    cfg = ctx.cfg
    releases = sorted(
        (p for p in cfg.releases_dir.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    kept: list[str] = []
    for rel in releases:
        if rel.name in keep_tags or len(kept) < cfg.keep_releases:
            kept.append(rel.name)
            continue
        shutil.rmtree(rel, ignore_errors=True)
    ctx.docker.prune_images({cfg.image_ref(t) for t in kept})


def deploy(
    ctx: Context,
    tag: str,
    *,
    force: bool = False,
    skip_migrations: bool = False,
    action: str = "deploy",
    allow_auto_rollback: bool = True,
) -> int:
    cfg = ctx.cfg
    out = ctx.out
    validate_tag(tag)
    _ensure_dirs(cfg)
    _check_config_files(cfg)

    started = ctx.clock()
    log_file = cfg.logs_dir / f"{action}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{tag}.log"
    ctx.docker.runner.log_file = log_file
    ctx.docker.runner.log(f"# {action} {tag} da {ctx.actor} il {now_iso()}")

    current = ctx.state.current()
    out.line(f"{action.capitalize()} di {cfg.name} ({cfg.environment}) -> {tag}")
    if current:
        out.line(f"Versione attuale: {current.tag} ({current.version})")

    record = DeploymentRecord(
        application=cfg.name,
        environment=cfg.environment,
        image=cfg.image_ref(tag),
        tag=tag,
        actor=ctx.actor,
        action=action,
        result="started",
    )
    ctx.state.acquire_lock(f"{action} {tag} da {ctx.actor}")
    try:
        # 1. immagine + bundle
        image = pull_and_extract(ctx, tag)
        record.digest = ctx.docker.image_digest(image)
        activate_release(ctx, tag)

        # 2. validazione compose
        r = ctx.docker.compose_config_check()
        if not r.ok:
            raise UsageError(
                "configurazione compose non valida: " + r.stderr.strip().splitlines()[-1][:300],
                "controllare config/app.env, secrets/app.secrets.env e app.conf",
            )

        # 3. idempotenza
        info = container_info(ctx)
        if (
            not force
            and current
            and current.tag == tag
            and info.status == "running"
            and info.image in (image, record.digest)
        ):
            ok, _ = wait_healthy(ctx, timeout=10)
            if ok:
                out.line(f"Versione {tag} gia' in esecuzione e sana: nessuna modifica.")
                ctx.audit.record(action, tag, "success", "gia' in esecuzione (idempotente)")
                return EXIT_OK

        ctx.state.append_history(record)
        ctx.audit.record(action, tag, "started", f"immagine {image}")

        # 4. migrazioni (solo deploy; il rollback non tocca lo schema, vedi docs/ROLLBACK.md)
        if not skip_migrations:
            run_migrations(ctx, tag)

        # 5. avvio
        out.step("avvio i container")
        r = ctx.docker.compose_up(force_recreate=force)
        if not r.ok:
            err = (r.stderr or r.stdout).strip().splitlines()
            failure = "docker compose up fallito: " + (err[-1] if err else "?")[:300]
        else:
            out.step(f"verifico health (timeout {cfg.health_timeout}s)")
            ok, failure = wait_healthy(ctx)
            if ok:
                failure = ""

        if not failure:
            live = fetch_version(ctx)
            labels = ctx.docker.image_labels(image)
            record.version = live.get("version") or labels.get(
                "org.opencontainers.image.version", "unknown"
            )
            record.commit = live.get("commit") or labels.get(
                "org.opencontainers.image.revision", "unknown"
            )
            record.result = "success"
            record.duration_s = round(ctx.clock() - started, 1)
            record.timestamp = now_iso()
            ctx.state.set_current(record)
            ctx.state.append_history(record)
            _update_current_link(cfg, tag)
            ctx.audit.record(
                action, tag, "success", f"versione {record.version} commit {record.commit}"
            )
            keep = {tag} | ({current.tag} if current else set())
            prune_releases(ctx, keep)
            out.line("")
            out.line(
                f"{action.capitalize()} completato: {cfg.name} {record.version} ({tag}) e' HEALTHY."
            )
            out.line(f"Log dettagliato: {log_file}")
            return EXIT_OK

        # ------------------------------------------------------------- fallimento
        diag = _diagnostics(ctx)
        ctx.docker.runner.log("### DIAGNOSTICA\n" + diag)
        record.result = "failed"
        record.detail = failure
        record.duration_s = round(ctx.clock() - started, 1)
        ctx.state.append_history(record)
        ctx.audit.record(action, tag, "failed", failure)
        out.line("")
        out.error(f"{action} di {tag} FALLITO: {failure}")
        out.line(f"Log dettagliato e diagnostica: {log_file}")

        previous = current if (current and current.tag != tag) else ctx.state.previous()
        if (
            allow_auto_rollback
            and cfg.auto_rollback
            and previous
            and _release_ready(cfg, previous.tag)
        ):
            out.line(f"Rollback automatico alla versione precedente {previous.tag} ...")
            rb = DeploymentRecord(
                application=cfg.name,
                environment=cfg.environment,
                image=previous.image,
                tag=previous.tag,
                version=previous.version,
                commit=previous.commit,
                actor=ctx.actor,
                action="rollback",
                result="started",
                detail=f"automatico dopo {action} fallito di {tag}",
            )
            activate_release(ctx, previous.tag)
            r = ctx.docker.compose_up(force_recreate=True)
            ok, why = wait_healthy(ctx) if r.ok else (False, r.stderr.strip()[-300:])
            rb.duration_s = round(ctx.clock() - started, 1)
            if ok:
                rb.result = "success"
                rb.timestamp = now_iso()
                ctx.state.set_current(rb)
                ctx.state.append_history(rb)
                _update_current_link(cfg, previous.tag)
                ctx.audit.record("rollback", previous.tag, "success", rb.detail)
                out.line(
                    f"Rollback riuscito: {cfg.name} {previous.version} ({previous.tag}) e' HEALTHY."
                )
                return EXIT_DEPLOY_ROLLED_BACK
            rb.result = "failed"
            rb.detail = why
            ctx.state.append_history(rb)
            ctx.audit.record("rollback", previous.tag, "failed", why)
            out.error(
                f"anche il rollback e' fallito: {why}",
                "APPLICAZIONE NON DISPONIBILE: seguire docs/RUNBOOK.md",
            )
            return EXIT_DEPLOY_DOWN
        if allow_auto_rollback and cfg.auto_rollback and not previous:
            out.warn("nessuna versione precedente disponibile per il rollback automatico")
        elif allow_auto_rollback and not cfg.auto_rollback:
            out.warn(
                "rollback automatico disabilitato (AUTO_ROLLBACK=false): eseguire 'appctl rollback' se necessario"
            )
        return EXIT_DEPLOY_DOWN
    finally:
        ctx.state.release_lock()
        ctx.docker.runner.log_file = None


def rollback(ctx: Context, tag: str | None = None) -> int:
    cfg = ctx.cfg
    current = ctx.state.current()
    if tag is None:
        previous = ctx.state.previous()
        if previous is None:
            raise AppctlError(
                "nessuna versione precedente registrata",
                hint="specificare il tag: appctl rollback <tag>  (vedere: appctl history)",
            )
        tag = previous.tag
    validate_tag(tag)
    if current and current.tag == tag:
        info = container_info(ctx)
        if info.status == "running":
            ctx.out.line(f"La versione {tag} e' gia' quella in esecuzione: nessuna modifica.")
            return EXIT_OK
    if not _release_ready(cfg, tag):
        ctx.out.step(f"release {tag} non presente localmente: la recupero dal registry")
    code = deploy(
        ctx, tag, force=True, skip_migrations=True, action="rollback", allow_auto_rollback=False
    )
    if code == EXIT_OK:
        ctx.out.line(
            "Nota: lo schema del database NON viene riportato indietro (docs/ROLLBACK.md)."
        )
    return code


# ============================================================================ lifecycle
def start(ctx: Context) -> int:
    cur = require_current(ctx)
    ctx.out.line(f"Avvio {ctx.cfg.name} ({cur.tag}) ...")
    r = ctx.docker.compose_up()
    if not r.ok:
        ctx.audit.record("start", cur.tag, "failed", r.stderr.strip()[-200:])
        raise AppctlError("avvio fallito: " + r.stderr.strip().splitlines()[-1][:300])
    ok, why = wait_healthy(ctx)
    ctx.audit.record("start", cur.tag, "success" if ok else "failed", why)
    if not ok:
        ctx.out.error(f"applicazione avviata ma non sana: {why}", "vedere: appctl logs --tail 200")
        return EXIT_UNHEALTHY
    ctx.out.line(f"{ctx.cfg.name} avviata e HEALTHY.")
    return EXIT_OK


def stop(ctx: Context) -> int:
    cur = require_current(ctx)
    ctx.out.line(f"Arresto {ctx.cfg.name} ({cur.tag}) ...")
    r = ctx.docker.compose_stop()
    ctx.audit.record("stop", cur.tag, "success" if r.ok else "failed", r.stderr.strip()[-200:])
    if not r.ok:
        raise AppctlError("arresto fallito: " + r.stderr.strip().splitlines()[-1][:300])
    ctx.out.line(
        f"{ctx.cfg.name} arrestata (non ripartira' al reboot finche' non si esegue 'appctl start')."
    )
    return EXIT_OK


def restart(ctx: Context, recreate: bool = False) -> int:
    cur = require_current(ctx)
    ctx.out.line(f"Riavvio {ctx.cfg.name} ({cur.tag}) ...")
    r = ctx.docker.compose_up(force_recreate=True) if recreate else ctx.docker.compose_restart()
    if not r.ok:
        ctx.audit.record("restart", cur.tag, "failed", r.stderr.strip()[-200:])
        raise AppctlError("riavvio fallito: " + r.stderr.strip().splitlines()[-1][:300])
    ok, why = wait_healthy(ctx)
    ctx.audit.record("restart", cur.tag, "success" if ok else "failed", why)
    if not ok:
        ctx.out.error(f"riavviata ma non sana: {why}", "vedere: appctl logs --tail 200")
        return EXIT_UNHEALTHY
    ctx.out.line(f"{ctx.cfg.name} riavviata e HEALTHY.")
    return EXIT_OK


# ============================================================================ info
def status(ctx: Context) -> int:
    cfg = ctx.cfg
    cur = ctx.state.current()
    prev = ctx.state.previous()
    info = container_info(ctx)
    ready = ctx.http.get(cfg.ready_url) if info.status == "running" else None
    data = {
        "application": cfg.name,
        "environment": cfg.environment,
        "version": cur.version if cur else "-",
        "tag": cur.tag if cur else "-",
        "image": cur.image if cur else "-",
        "commit": cur.commit if cur else "-",
        "status": info.display_status,
        "health": info.display_health,
        "ready": (ready.ok if ready else False),
        "started": fmt_ts(info.started_at) if info.status == "running" else "-",
        "restart_count": info.restart_count,
        "container": cfg.app_container if info.exists else "-",
        "deployed_by": cur.actor if cur else "-",
        "deployed_at": fmt_ts(cur.timestamp) if cur else "-",
        "previous": prev.tag if prev else "-",
    }
    ctx.out.json(data)
    ctx.out.kv(
        [
            ("Application", data["application"]),
            ("Environment", data["environment"]),
            ("Version", data["version"]),
            ("Image", data["image"]),
            ("Commit", data["commit"]),
            ("Status", data["status"]),
            (
                "Health",
                data["health"]
                + ("" if not ready else (" (ready)" if ready.ok else " (NOT READY)")),
            ),
            ("Started", data["started"]),
            ("Container", data["container"]),
            ("Deployed by", data["deployed_by"]),
            ("Deployed at", data["deployed_at"]),
            ("Previous", data["previous"] + (" (target di rollback)" if prev else "")),
        ]
    )
    if info.restart_count:
        ctx.out.line(f"Nota: il container e' stato riavviato {info.restart_count} volte da Docker.")
    return EXIT_OK


def health(ctx: Context, wait: int = 0) -> int:
    cfg = ctx.cfg
    deadline = ctx.clock() + wait
    while True:
        info = container_info(ctx)
        h = ctx.http.get(cfg.health_url)
        r = ctx.http.get(cfg.ready_url)
        ok = info.status == "running" and info.health in ("healthy", "none") and h.ok and r.ok
        if ok or ctx.clock() >= deadline:
            break
        ctx.sleep(cfg.health_interval)
    checks = (r.body or {}).get("checks", {}) if r.body else {}
    data = {
        "started": info.status == "running",
        "alive": h.ok,
        "ready": r.ok,
        "docker_health": info.health,
        "dependencies": checks,
        "healthy": ok,
    }
    ctx.out.json(data)
    rows = [
        ("Application", cfg.name),
        ("Started", "yes" if data["started"] else f"no ({info.display_status})"),
        ("Alive (/health)", "yes" if h.ok else f"no ({h.status or h.error or 'nessuna risposta'})"),
        ("Ready (/ready)", "yes" if r.ok else f"no ({r.status or r.error or 'nessuna risposta'})"),
        ("Docker health", info.display_health),
    ]
    for name, chk in checks.items():
        state = "ok" if chk.get("ok") else f"FAIL ({chk.get('error', '?')})"
        rows.append((f"Dependency {name}", state))
    rows.append(("Overall", "HEALTHY" if ok else "UNHEALTHY"))
    ctx.out.kv(rows)
    return EXIT_OK if ok else EXIT_UNHEALTHY


def version(ctx: Context) -> int:
    cfg = ctx.cfg
    cur = ctx.state.current()
    prev = ctx.state.previous()
    live = fetch_version(ctx)
    data = {
        "application": cfg.name,
        "environment": cfg.environment,
        "current": cur.to_dict() if cur else None,
        "previous": prev.to_dict() if prev else None,
        "running": live or None,
    }
    ctx.out.json(data)
    ctx.out.line("CURRENT DEPLOYMENT")
    ctx.out.kv(
        [
            ("Application", cfg.name),
            ("Environment", cfg.environment),
            ("Version", (cur.version if cur else "-")),
            ("Commit", (cur.commit if cur else "-")),
            ("Image", (cur.image if cur else "-")),
            ("Digest", (cur.digest or "-") if cur else "-"),
            ("Deployed by", (cur.actor if cur else "-")),
            ("Deployed at", fmt_ts(cur.timestamp) if cur else "-"),
            (
                "Running now",
                f"{live.get('version', '?')} commit {live.get('commit', '?')}"
                if live
                else "non risponde",
            ),
            ("Previous", f"{prev.version} ({prev.tag})" if prev else "-"),
        ]
    )
    if cur and live and live.get("commit") not in (None, cur.commit):
        ctx.out.warn(
            "la versione in esecuzione non coincide con quella registrata: verificare con appctl history"
        )
    return EXIT_OK


def history(ctx: Context, limit: int = 20) -> int:
    rows = ctx.state.history(limit)
    ctx.out.json([r.to_dict() for r in rows])
    if not rows:
        ctx.out.line("Nessun deployment registrato.")
        return EXIT_OK
    ctx.out.table(
        ["Quando", "Azione", "Tag", "Versione", "Chi", "Esito", "Durata"],
        [
            [
                fmt_ts(r.timestamp),
                r.action,
                r.tag,
                r.version,
                r.actor,
                r.result,
                f"{r.duration_s:.0f}s" if r.duration_s is not None else "-",
            ]
            for r in rows
        ],
    )
    return EXIT_OK


def logs(
    ctx: Context,
    *,
    follow: bool = False,
    since: str | None = None,
    tail: int = 200,
    service: str | None = None,
    all_services: bool = False,
    deploy_log: bool = False,
    audit_log: bool = False,
) -> int:
    cfg = ctx.cfg
    if audit_log:
        path = cfg.audit_log
        if not path.is_file():
            ctx.out.line(f"nessun audit log in {path}")
            return EXIT_OK
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]
        print("\n".join(lines))
        return EXIT_OK
    if deploy_log:
        files = sorted(cfg.logs_dir.glob("*.log")) if cfg.logs_dir.is_dir() else []
        if not files:
            ctx.out.line("nessun log di deploy presente")
            return EXIT_OK
        latest = files[-1]
        ctx.out.line(f"=== {latest} ===")
        print(latest.read_text(encoding="utf-8", errors="replace"))
        return EXIT_OK
    require_current(ctx)
    args = ["--tail", str(tail), "--timestamps"]
    if follow:
        args.append("--follow")
    if since:
        args += ["--since", since]
    if service:
        args.append(service)
    elif not all_services:
        args.append(cfg.app_service)
    r = ctx.docker.compose_logs(args)
    return EXIT_OK if r.ok else EXIT_FAILURE


# ============================================================================ doctor
@dataclass
class Check:
    name: str
    level: str  # PASS | WARN | FAIL
    message: str


def _disk(path: Path) -> tuple[float, str]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return -1.0, "n/d"
    pct = usage.used / usage.total * 100 if usage.total else 0.0
    free_gb = usage.free / (1024**3)
    return pct, f"{pct:.0f}% usato, {free_gb:.1f} GB liberi"


def _memory() -> tuple[float, str]:
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        return -1.0, "n/d"
    values: dict[str, int] = {}
    for line in meminfo.read_text().splitlines():
        key, _, rest = line.partition(":")
        values[key] = int(rest.split()[0]) if rest.split() else 0
    total = values.get("MemTotal", 0)
    avail = values.get("MemAvailable", 0)
    if not total:
        return -1.0, "n/d"
    pct = avail / total * 100
    return pct, f"{avail / 1024:.0f} MB disponibili su {total / 1024:.0f} MB"


def doctor(ctx: Context) -> int:
    cfg = ctx.cfg
    checks: list[Check] = []

    def add(name: str, ok: bool | None, msg: str, warn: bool = False) -> None:
        level = "PASS" if ok else ("WARN" if warn or ok is None else "FAIL")
        checks.append(Check(name, level, msg))

    # Docker
    try:
        v = ctx.docker.ping()
        add("Docker Engine", True, f"versione {v}")
        cv = ctx.docker.compose_version()
        add("Docker Compose", True, f"versione {cv}")
    except AppctlError as exc:
        add("Docker Engine", False, exc.message)

    # Configurazione
    add("Manifest app.conf", True, f"{cfg.app_dir / 'app.conf'} ({cfg.environment})")
    add("Config app.env", cfg.app_env_file.is_file(), str(cfg.app_env_file))
    if cfg.secrets_file.is_file():
        mode = stat.S_IMODE(cfg.secrets_file.stat().st_mode)
        add(
            "Secrets permessi",
            mode & 0o077 == 0,
            f"{cfg.secrets_file} mode {oct(mode)}"
            + ("" if mode & 0o077 == 0 else " (atteso 0600)"),
        )
    else:
        add("Secrets", False, f"{cfg.secrets_file} mancante")

    # Stato e release
    cur = ctx.state.current()
    if cur:
        add(
            "Deployment corrente",
            True,
            f"{cur.tag} ({cur.version}) da {cur.actor} il {fmt_ts(cur.timestamp)}",
        )
        add("Release corrente", _release_ready(cfg, cur.tag), str(cfg.release_dir(cur.tag)))
        try:
            activate_release(ctx, cur.tag)
            r = ctx.docker.compose_config_check()
            add("Compose config", r.ok, "valida" if r.ok else r.stderr.strip()[-200:])
        except AppctlError as exc:
            add("Compose config", False, exc.message)
        add("Immagine locale", ctx.docker.image_exists_locally(cur.image), cur.image)
    else:
        add("Deployment corrente", None, "nessuno (eseguire appctl deploy <tag>)", warn=True)
    prev = ctx.state.previous()
    add(
        "Rollback disponibile",
        prev is not None and _release_ready(cfg, prev.tag),
        prev.tag if prev else "nessuna versione precedente",
        warn=prev is None,
    )

    # Container
    info = container_info(ctx)
    if info.exists:
        add(
            "Container app",
            info.status == "running",
            f"{cfg.app_container}: {info.display_status}, health {info.display_health}",
        )
        add(
            "Riavvii container",
            info.restart_count < 3,
            f"{info.restart_count} riavvii automatici",
            warn=info.restart_count >= 3,
        )
        log_ok = info.log_driver == "json-file" and "max-size" in info.log_opts
        add(
            "Rotazione log",
            log_ok,
            f"driver {info.log_driver or '?'} {info.log_opts or ''}",
            warn=not log_ok,
        )
    else:
        add("Container app", None, "non presente", warn=True)
    if cfg.db_service:
        db = container_info(ctx, f"{cfg.name}-{cfg.db_service}")
        add(
            "Container db",
            db.status == "running",
            f"{cfg.name}-{cfg.db_service}: {db.display_status}, health {db.display_health}",
        )

    # Health
    h = ctx.http.get(cfg.health_url)
    r = ctx.http.get(cfg.ready_url)
    add("Health /health", h.ok, f"{cfg.health_url} -> {h.status or h.error}")
    add("Ready /ready", r.ok, f"{cfg.ready_url} -> {r.status or r.error}")

    # Rete
    try:
        with socket.create_connection(("127.0.0.1", cfg.app_port), timeout=2):
            add("Porta locale", True, f"127.0.0.1:{cfg.app_port} in ascolto")
    except OSError:
        add("Porta locale", False, f"127.0.0.1:{cfg.app_port} non raggiungibile")
    if any(f.endswith(("dev.yaml", "prod.yaml")) for f in cfg.compose_files):
        add("Rete proxy", ctx.docker.network_exists("proxy"), "rete docker 'proxy' (reverse proxy)")

    # Registry (loopback in chiaro, come le insecure-registries di default di Docker)
    reg_host = cfg.registry_host.split(":")[0]
    scheme = (
        "http" if reg_host in ("localhost", "127.0.0.1") or reg_host.startswith("127.") else "https"
    )
    reg_url = f"{scheme}://{cfg.registry_host}/v2/"
    reg = ctx.http.get(reg_url, timeout=5)
    add("Registry", reg.status in (200, 401), f"{reg_url} -> {reg.status or reg.error}")

    # Risorse
    for label, path in (("Disco /", Path("/")), ("Disco app", cfg.app_dir)):
        pct, msg = _disk(path)
        if pct < 0:
            continue
        add(label, pct < 90, msg, warn=80 <= pct < 90)
    mpct, mmsg = _memory()
    if mpct >= 0:
        add("Memoria", mpct > 5, mmsg, warn=5 < mpct <= 15)

    # Audit
    add(
        "Audit log",
        os.access(cfg.audit_log, os.W_OK) if cfg.audit_log.exists() else False,
        str(cfg.audit_log),
        warn=not cfg.audit_log.exists(),
    )

    # Certificati
    if cfg.public_url.startswith("https://"):
        host = urlparse(cfg.public_url).hostname or ""
        days = ctx.http.tls_days_left(host)
        if days is None:
            add("Certificato TLS", None, f"{host}: non verificabile", warn=True)
        else:
            add(
                "Certificato TLS", days > 7, f"{host}: scade tra {days} giorni", warn=7 < days <= 21
            )

    # Backup
    if cfg.backups_dir.is_dir():
        files = sorted(cfg.backups_dir.glob("db-*.sql.gz"))
        if files:
            age = datetime.now() - datetime.fromtimestamp(files[-1].stat().st_mtime)
            add(
                "Ultimo backup DB",
                age < timedelta(days=2),
                f"{files[-1].name} ({age.days} giorni fa)",
                warn=age >= timedelta(days=2),
            )
        elif cfg.db_service:
            add("Ultimo backup DB", None, "nessun backup presente", warn=True)

    ctx.out.json([c.__dict__ for c in checks])
    for c in checks:
        ctx.out.line(f"[{c.level:4}] {c.name:<22} {c.message}")
    fails = sum(1 for c in checks if c.level == "FAIL")
    warns = sum(1 for c in checks if c.level == "WARN")
    ctx.out.line("")
    ctx.out.line(
        f"Esito: {fails} problemi, {warns} avvisi, {len(checks) - fails - warns} controlli OK"
    )
    return EXIT_FAILURE if fails else EXIT_OK


# ============================================================================ backup
def backup(ctx: Context, quiet: bool = False) -> int:
    cfg = ctx.cfg
    cfg.backups_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    produced: list[Path] = []

    if cfg.db_service:
        cur = ctx.state.current()
        if cur and ctx.docker.release_dir is None:
            # backup autonomo (appctl backup): usa la release corrente; dentro un deploy la
            # release attiva e' gia' quella giusta e non va cambiata
            activate_release(ctx, cur.tag)
        db_info = container_info(ctx, f"{cfg.name}-{cfg.db_service}")
        if db_info.status != "running" or not cur:
            ctx.out.warn("database non in esecuzione: backup DB saltato")
        else:
            secrets = parse_env_file(cfg.secrets_file)
            user = secrets.get("POSTGRES_USER", "postgres")
            dbname = secrets.get("POSTGRES_DB", user)
            r = ctx.docker.compose_exec(
                cfg.db_service,
                [
                    "pg_dump",
                    "-U",
                    user,
                    "-d",
                    dbname,
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-privileges",
                ],
            )
            if not r.ok:
                ctx.audit.record(
                    "backup", cur.tag if cur else "-", "failed", r.stderr.strip()[-200:]
                )
                raise AppctlError("pg_dump fallito: " + r.stderr.strip().splitlines()[-1][:300])
            target = cfg.backups_dir / f"db-{ts}.sql.gz"
            with gzip.open(target, "wt", encoding="utf-8") as fh:
                fh.write(r.stdout)
            os.chmod(target, 0o600)
            produced.append(target)

    config_target = cfg.backups_dir / f"config-{ts}.tar.gz"
    with tarfile.open(config_target, "w:gz") as tar:
        for item in ("app.conf", "config", "secrets", "state"):
            p = cfg.app_dir / item
            if p.exists():
                tar.add(p, arcname=item)
    os.chmod(config_target, 0o600)
    produced.append(config_target)

    # retention
    cutoff = time.time() - cfg.backup_keep_days * 86400
    removed = 0
    for old in cfg.backups_dir.iterdir():
        if old.is_file() and old.stat().st_mtime < cutoff:
            old.unlink()
            removed += 1

    cur = ctx.state.current()
    ctx.audit.record(
        "backup", cur.tag if cur else "-", "success", ", ".join(p.name for p in produced)
    )
    if not quiet:
        for p in produced:
            ctx.out.line(f"Backup creato: {p} ({p.stat().st_size // 1024} KB)")
        ctx.out.line(f"Retention: {cfg.backup_keep_days} giorni ({removed} file rimossi)")
    return EXIT_OK


def restore(ctx: Context, backup_file: str, confirmed: bool = False) -> int:
    cfg = ctx.cfg
    path = Path(backup_file)
    if not path.is_absolute():
        path = cfg.backups_dir / path
    if not path.is_file() or not path.name.endswith(".sql.gz"):
        raise UsageError(
            f"file di backup non valido: {path}", "attesi i file db-<data>.sql.gz in backups/"
        )
    if not confirmed:
        raise UsageError(
            "il restore SOVRASCRIVE il database corrente",
            f"per confermare: appctl restore {path.name} --yes",
        )
    if not cfg.db_service:
        raise UsageError("nessun DB_SERVICE configurato: restore da eseguire sul database esterno")
    cur = require_current(ctx)
    secrets = parse_env_file(cfg.secrets_file)
    user = secrets.get("POSTGRES_USER", "postgres")
    dbname = secrets.get("POSTGRES_DB", user)

    ctx.out.step("fermo l'applicazione")
    ctx.docker.compose("stop", cfg.app_service, timeout=300)
    ctx.docker.compose_up(cfg.db_service)
    ctx.out.step(f"ripristino {path.name}")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        sql = fh.read()
    r = ctx.docker.compose_exec(
        cfg.db_service,
        ["psql", "-U", user, "-d", dbname, "-v", "ON_ERROR_STOP=1", "-q"],
        input_text=sql,
    )
    if not r.ok:
        ctx.audit.record("restore", cur.tag, "failed", r.stderr.strip()[-200:])
        raise AppctlError(
            "restore fallito: " + r.stderr.strip().splitlines()[-1][:300],
            hint="applicazione ferma: valutare 'appctl start' o un altro backup",
        )
    ctx.out.step("riavvio l'applicazione")
    ctx.docker.compose_up()
    ok, why = wait_healthy(ctx)
    ctx.audit.record(
        "restore", cur.tag, "success" if ok else "failed", path.name + ("" if ok else f" ({why})")
    )
    if not ok:
        ctx.out.error(f"restore eseguito ma applicazione non sana: {why}")
        return EXIT_UNHEALTHY
    ctx.out.line(f"Restore di {path.name} completato, applicazione HEALTHY.")
    return EXIT_OK


def show_config(ctx: Context) -> int:
    cfg = ctx.cfg
    data = dict(cfg.raw)
    data["APP_DIR"] = str(cfg.app_dir)
    ctx.out.json(data)
    ctx.out.kv(sorted(data.items()))
    return EXIT_OK


__all__ = [
    "Context",
    "EXIT_USAGE",
    "backup",
    "deploy",
    "doctor",
    "health",
    "history",
    "logs",
    "restart",
    "restore",
    "rollback",
    "show_config",
    "start",
    "status",
    "stop",
    "version",
]
