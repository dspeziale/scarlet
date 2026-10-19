"""Command line entry points.

pkm-server  - runs the web application (used by pkm.service)
pkm-admin   - administration: users, setup token, backup/verify/restore, configuration check
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, Settings, load_settings
from .logging_setup import setup_logging


def _load(args: argparse.Namespace) -> Settings:
    try:
        return load_settings(getattr(args, "config", None))
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)


def server_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pkm-server", description="Scarlet web server")
    parser.add_argument("--config", help="configuration file (default: $PKM_CONFIG or /etc/pkm/config.yaml)")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    settings = _load(args)
    setup_logging(settings.logging)
    import uvicorn

    from .main import create_app

    app = create_app(settings)
    srv = settings.server
    uvicorn.run(
        app,
        host=srv.host,
        port=srv.port,
        ssl_certfile=srv.tls_cert,
        ssl_keyfile=srv.tls_key,
        proxy_headers=bool(srv.trusted_proxies),
        forwarded_allow_ips=",".join(srv.trusted_proxies) or None,
        timeout_graceful_shutdown=srv.graceful_shutdown_seconds,
        timeout_keep_alive=10,
        log_config=None,
        access_log=False,
        server_header=False,
    )


# ------------------------------------------------------------------ admin
def _ctx_light(settings: Settings):  # type: ignore[no-untyped-def]
    from .audit import AuditService
    from .db import Database
    from .runtime_settings import RuntimeSettings
    from .security.users import UserService

    db = Database(settings.database.path)
    db.migrate()
    eff = RuntimeSettings(db, settings).effective()
    return db, eff, UserService(db, eff.auth), AuditService(db)


def _read_password(args: argparse.Namespace, username: str, users) -> str:  # type: ignore[no-untyped-def]
    if getattr(args, "password_stdin", False):
        pw = sys.stdin.readline().rstrip("\n")
    else:
        pw = getpass.getpass(f"New password for {username}: ")
        if getpass.getpass("Repeat password: ") != pw:
            print("ERROR: passwords do not match", file=sys.stderr)
            sys.exit(1)
    return pw


def _cli_audit(audit, action: str, **kw) -> None:  # type: ignore[no-untyped-def]
    from .audit import AuditContext

    user = os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"
    audit.record(AuditContext(None, f"cli:{user}", user_agent="pkm-admin"), action, **kw)


def admin_main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pkm-admin", description="Scarlet administration")
    parser.add_argument("--config", help="configuration file (default: $PKM_CONFIG or /etc/pkm/config.yaml)")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin", help="create an administrator account")
    p.add_argument("--username", required=True)
    p.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    p = sub.add_parser("reset-password", help="set a new password for a user and unlock the account")
    p.add_argument("username")
    p.add_argument("--password-stdin", action="store_true")
    p = sub.add_parser("unlock", help="unlock a user locked by failed logins")
    p.add_argument("username")
    sub.add_parser("list-users", help="list users")
    sub.add_parser("setup-token", help="(re)generate the one-time setup token for the first-run wizard")
    p = sub.add_parser("backup", help="create a backup archive")
    p.add_argument("--scheduled", action="store_true", help="mark as scheduled (used by pkm-backup.timer)")
    p.add_argument("--include-manifests", action="store_true", default=None, help="also export Kubernetes manifests")
    p = sub.add_parser("verify-backup", help="verify a backup archive")
    p.add_argument("file")
    p = sub.add_parser("restore", help="restore a backup (the service must be stopped)")
    p.add_argument("file")
    p.add_argument("--with-config", action="store_true", help="also restore config.yaml and pkm.env")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    sub.add_parser("check-config", help="validate the configuration and print the effective values")
    sub.add_parser("purge-audit", help="delete audit entries older than the retention period")
    sub.add_parser("migrate", help="apply database migrations")
    args = parser.parse_args(argv)
    settings = _load(args)

    if args.cmd == "check-config":
        data = settings.model_dump()
        if data["monitoring"].get("prometheus_token"):
            data["monitoring"]["prometheus_token"] = "********"  # noqa: S105 - mask, not a password
        print(json.dumps({"config_file": settings.config_file, "settings": data}, indent=2, default=str))
        problems = []
        if settings.server.tls_enabled:
            for f in (settings.server.tls_cert, settings.server.tls_key):
                if not Path(str(f)).is_file():
                    problems.append(f"TLS file not found: {f}")
        if settings.kubernetes.enabled and not settings.kubernetes.in_cluster and settings.kubernetes.kubeconfig and \
                not Path(settings.kubernetes.kubeconfig).is_file():  # fmt: skip
            problems.append(f"kubeconfig not found: {settings.kubernetes.kubeconfig}")
        for p_ in problems:
            print(f"WARNING: {p_}", file=sys.stderr)
        print("configuration OK" if not problems else "configuration loaded with warnings")
        return

    db, eff, users, audit = _ctx_light(settings)

    if args.cmd == "migrate":
        print(f"database schema version {db.schema_version()}")
    elif args.cmd == "create-admin":
        pw = _read_password(args, args.username, users)
        try:
            u = users.create(args.username, pw, "admin", must_change_password=False)
        except Exception as exc:
            print(f"ERROR: {getattr(exc, 'message', exc)} {getattr(exc, 'params', '')}", file=sys.stderr)
            sys.exit(1)
        _cli_audit(audit, "user.create", kind="User", name=u.username, detail={"role": "admin"})
        db.set_state("setup_token_hash", None)
        print(f"administrator '{u.username}' created")
    elif args.cmd == "reset-password":
        u = users.get_by_username(args.username)
        if not u:
            print("ERROR: user not found", file=sys.stderr)
            sys.exit(1)
        pw = _read_password(args, u.username, users)
        try:
            users.set_password(u.id, pw, must_change=False)
        except Exception as exc:
            print(f"ERROR: {getattr(exc, 'message', exc)} {getattr(exc, 'params', '')}", file=sys.stderr)
            sys.exit(1)
        _cli_audit(audit, "user.password_reset", kind="User", name=u.username)
        print(f"password of '{u.username}' updated, account unlocked, sessions revoked")
    elif args.cmd == "unlock":
        u = users.get_by_username(args.username)
        if not u:
            print("ERROR: user not found", file=sys.stderr)
            sys.exit(1)
        users.unlock(u.id)
        _cli_audit(audit, "user.unlock", kind="User", name=u.username)
        print(f"'{u.username}' unlocked")
    elif args.cmd == "list-users":
        for u in users.list():
            print(f"{u.username:<24} {u.role:<9} {'active' if u.active else 'disabled':<8} last login: {u.last_login_at or '-'}")
    elif args.cmd == "setup-token":
        if users.count() > 0:
            print("ERROR: setup already completed (users exist). Use create-admin or reset-password.", file=sys.stderr)
            sys.exit(1)
        from .security.users import new_setup_token

        print(new_setup_token(db))
    elif args.cmd == "backup":
        from .backup import BackupService

        include = eff.backup.include_manifests if args.include_manifests is None else args.include_manifests
        k8s = None
        if include:
            from .k8s.service import KubernetesService, build_provider

            k8s = KubernetesService(build_provider(eff), eff.kubernetes)
        svc = BackupService(db, eff.backup.directory, settings.config_file)
        try:
            res = svc.create(trigger="scheduled" if args.scheduled else "manual", user="cli", include_manifests=include,
                             k8s=k8s)  # fmt: skip
        except Exception as exc:
            _cli_audit(audit, "backup.create", result="failure", kind="Backup", detail={"error": str(exc)[:300]})
            print(f"ERROR: backup failed: {exc}", file=sys.stderr)
            sys.exit(1)
        removed = svc.apply_retention(eff.backup.retention_count)
        _cli_audit(audit, "backup.create", kind="Backup", name=res["filename"],
                   detail={"scheduled": args.scheduled, "removedByRetention": removed})  # fmt: skip
        print(json.dumps({"file": str(Path(eff.backup.directory) / res["filename"]), "size": res["size_bytes"],
                          "sha256": res["sha256"], "includes": res["includes"], "removed": removed}, indent=2))  # fmt: skip
    elif args.cmd == "verify-backup":
        from .backup import BackupService

        res = BackupService(db, str(Path(args.file).parent), None).verify_file(Path(args.file))
        print(json.dumps({k: v for k, v in res.items() if k != "manifest"}, indent=2))
        sys.exit(0 if res["ok"] else 1)
    elif args.cmd == "restore":
        from .backup import restore_archive
        from .errors import AppError

        if not args.yes:
            ans = input(f"Restore {args.file} over {settings.database.path}? The service must be stopped. [yes/NO] ")
            if ans.strip().lower() != "yes":
                print("aborted")
                sys.exit(1)
        cfg_dir = str(Path(settings.config_file).parent) if settings.config_file else None
        try:
            res = restore_archive(Path(args.file), settings.database.path, config_dir=cfg_dir, with_config=args.with_config)
        except AppError as exc:
            print(f"ERROR: {exc.message}", file=sys.stderr)
            print(json.dumps(exc.params, indent=2), file=sys.stderr)
            sys.exit(1)
        # The audit entry goes into the restored database, so the restore itself is traceable.
        _, _, _, audit2 = _ctx_light(settings)
        _cli_audit(audit2, "backup.restore", kind="Backup", name=Path(args.file).name,
                   detail={"withConfig": args.with_config, "restored": res["restored"]})  # fmt: skip
        print(json.dumps({"restored": res["restored"], "previous_copies_suffix": res["previous_suffix"]}, indent=2))
    elif args.cmd == "purge-audit":
        n = audit.purge(eff.audit.retention_days)
        print(f"{n} audit entries older than {eff.audit.retention_days} days deleted")


if __name__ == "__main__":  # pragma: no cover
    admin_main()
