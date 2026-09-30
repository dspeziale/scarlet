"""Riga di comando di appctl."""

from __future__ import annotations

import argparse
import os
import sys

from appctl import __version__, ops
from appctl.audit import AuditLog, current_actor
from appctl.config import load_config, resolve_app_dir
from appctl.errors import EXIT_DESCRIPTIONS, EXIT_FAILURE, EXIT_USAGE, AppctlError
from appctl.http import HttpProber
from appctl.output import Printer
from appctl.runner import CommandRunner, DockerClient
from appctl.state import StateStore

DESCRIPTION = """appctl - gestione operativa delle applicazioni Docker.

Comandi quotidiani:   status, start, stop, restart, logs, health, version
Rilasci:              deploy <tag>, rollback [tag], history
Diagnostica/backup:   doctor, backup, restore, config

Exit code: """ + ", ".join(f"{k}={v}" for k, v in EXIT_DESCRIPTIONS.items())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="appctl",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--app", help="nome applicazione (default: l'unica installata o APPCTL_APP)")
    p.add_argument("--app-dir", help="directory applicazione (default: /opt/apps/<app>)")
    p.add_argument(
        "--json", action="store_true", help="output JSON (status, health, version, history, doctor)"
    )
    p.add_argument(
        "--actor",
        help="identita' di chi opera (solo per la pipeline; per gli operatori viene usato l'utente sudo)",
    )
    p.add_argument("-V", "--version", action="version", version=f"appctl {__version__}")

    sub = p.add_subparsers(dest="command", metavar="comando")
    sub.required = True

    sub.add_parser("status", help="stato sintetico dell'applicazione")
    sub.add_parser("start", help="avvia l'applicazione (versione corrente)")
    sub.add_parser("stop", help="ferma l'applicazione")
    sp = sub.add_parser("restart", help="riavvia l'applicazione")
    sp.add_argument(
        "--recreate", action="store_true", help="ricrea i container (rilegge config/secrets)"
    )

    sp = sub.add_parser(
        "deploy", help="deploy di una versione (tag immagine, es. git-a1b2c3d4e5f6)"
    )
    sp.add_argument("tag")
    sp.add_argument(
        "--force", action="store_true", help="ricrea anche se la versione e' gia' attiva"
    )
    sp.add_argument("--skip-migrations", action="store_true", help="non eseguire le migrazioni DB")
    sp.add_argument(
        "--no-auto-rollback",
        action="store_true",
        help="in caso di fallimento non ripristinare la versione precedente",
    )

    sp = sub.add_parser("rollback", help="torna alla versione precedente (o a un tag specifico)")
    sp.add_argument("tag", nargs="?")

    sp = sub.add_parser("logs", help="log dell'applicazione")
    sp.add_argument("-f", "--follow", action="store_true")
    sp.add_argument("--since", help="es. 1h, 30m, 2026-09-30T10:00:00")
    sp.add_argument("--tail", type=int, default=200)
    sp.add_argument("--service", help="servizio compose (default: app)")
    sp.add_argument("--all", action="store_true", help="tutti i servizi (app, db, ...)")
    sp.add_argument("--deploy", action="store_true", help="ultimo log di deploy/rollback")
    sp.add_argument("--audit", action="store_true", help="audit log delle operazioni")

    sp = sub.add_parser("health", help="verifica health e readiness")
    sp.add_argument("--wait", type=int, default=0, help="attende fino a N secondi che diventi sana")

    sub.add_parser("version", help="versione, commit e immagine in esecuzione")
    sp = sub.add_parser("history", help="storico dei deployment")
    sp.add_argument("-n", "--limit", type=int, default=20)
    sub.add_parser(
        "doctor", help="diagnostica completa (Docker, disco, memoria, rete, registry, health...)"
    )
    sub.add_parser("backup", help="backup di database, configurazione e stato")
    sp = sub.add_parser("restore", help="ripristina un backup del database")
    sp.add_argument("file")
    sp.add_argument("--yes", action="store_true", help="conferma (operazione distruttiva)")
    sub.add_parser("config", help="mostra la configurazione effettiva (app.conf)")
    return p


def build_context(args: argparse.Namespace) -> ops.Context:
    app_dir = resolve_app_dir(args.app, args.app_dir)
    cfg = load_config(app_dir)
    out = Printer(as_json=args.json)

    actor = current_actor()
    if args.actor:
        if os.environ.get("SUDO_USER"):
            out.warn("--actor ignorato: l'identita' e' certificata da sudo")
        else:
            actor = args.actor.strip()[:128]

    runner = CommandRunner()
    docker = DockerClient(runner, project=cfg.name, compose_env=cfg.compose_env(image=""))
    state = StateStore(cfg.state_dir)
    audit = AuditLog(cfg.audit_log, cfg.name, cfg.environment, actor)
    return ops.Context(
        cfg=cfg, docker=docker, http=HttpProber(), state=state, audit=audit, out=out, actor=actor
    )


def dispatch(args: argparse.Namespace, ctx: ops.Context) -> int:
    cmd = args.command
    if cmd in (
        "status",
        "start",
        "stop",
        "deploy",
        "rollback",
        "logs",
        "health",
        "version",
        "history",
        "doctor",
        "backup",
        "restore",
    ):
        ctx.docker.ping()
    if cmd == "status":
        return ops.status(ctx)
    if cmd == "start":
        return ops.start(ctx)
    if cmd == "stop":
        return ops.stop(ctx)
    if cmd == "restart":
        return ops.restart(ctx, recreate=args.recreate)
    if cmd == "deploy":
        return ops.deploy(
            ctx,
            args.tag,
            force=args.force,
            skip_migrations=args.skip_migrations,
            allow_auto_rollback=not args.no_auto_rollback,
        )
    if cmd == "rollback":
        return ops.rollback(ctx, args.tag)
    if cmd == "logs":
        return ops.logs(
            ctx,
            follow=args.follow,
            since=args.since,
            tail=args.tail,
            service=args.service,
            all_services=args.all,
            deploy_log=args.deploy,
            audit_log=args.audit,
        )
    if cmd == "health":
        return ops.health(ctx, wait=args.wait)
    if cmd == "version":
        return ops.version(ctx)
    if cmd == "history":
        return ops.history(ctx, limit=args.limit)
    if cmd == "doctor":
        return ops.doctor(ctx)
    if cmd == "backup":
        return ops.backup(ctx)
    if cmd == "restore":
        return ops.restore(ctx, args.file, confirmed=args.yes)
    if cmd == "config":
        return ops.show_config(ctx)
    return EXIT_USAGE


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        ctx = build_context(args)
        return dispatch(args, ctx)
    except AppctlError as exc:
        print(f"ERRORE: {exc.message}", file=sys.stderr)
        if exc.hint:
            print(f"        {exc.hint}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("interrotto", file=sys.stderr)
        return EXIT_FAILURE
