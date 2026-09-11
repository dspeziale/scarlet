"""Flask CLI commands: ``flask scarlet <command>``."""

from __future__ import annotations

import os
import sys

import click
from flask import Flask
from flask.cli import AppGroup

scarlet_cli = AppGroup("scarlet", help="SCARLET administration commands.")


@scarlet_cli.command("gen-key")
def gen_key() -> None:
    """Generate a random key suitable for SCARLET_SECRET_KEY / SCARLET_CREDENTIAL_ENCRYPTION_KEY."""
    from app.security.crypto import CredentialCipher

    click.echo(CredentialCipher.generate_key())


@scarlet_cli.command("sync-rbac")
def sync_rbac() -> None:
    """Create/update the permission catalogue and system roles."""
    from app.services.user_service import UserService

    UserService().sync_permissions_and_roles()
    click.echo("Permissions and roles synchronized.")


@scarlet_cli.command("create-admin")
@click.option("--username", default="admin", show_default=True)
@click.option("--password", default=None, help="Defaults to SCARLET_INITIAL_ADMIN_PASSWORD.")
@click.option("--email", default=None)
def create_admin(username: str, password: str | None, email: str | None) -> None:
    """Create the initial administrator (password from SCARLET_INITIAL_ADMIN_PASSWORD)."""
    from app.repositories import UserRepository
    from app.security.rbac import ROLE_ADMIN
    from app.services.user_service import UserService

    password = password or os.environ.get("SCARLET_INITIAL_ADMIN_PASSWORD", "")
    if not password:
        click.echo("ERROR: provide --password or set SCARLET_INITIAL_ADMIN_PASSWORD.", err=True)
        sys.exit(2)
    service = UserService()
    service.sync_permissions_and_roles()
    if UserRepository().by_username(username):
        click.echo(f"User {username} already exists; nothing to do.")
        return
    service.create_user(
        username=username,
        password=password,
        roles=[ROLE_ADMIN],
        email=email,
        full_name="Administrator",
        must_change_password=True,
    )
    click.echo(f"Administrator '{username}' created. The password must be changed at first login.")


@scarlet_cli.command("seed")
@click.option(
    "--with-demo",
    is_flag=True,
    default=False,
    help="Also create demo hosts/applications/versions/audit events.",
)
def seed(with_demo: bool) -> None:
    """Seed environments, RBAC, admin and (optionally) development demo data."""
    from app.seed import seed_all

    summary = seed_all(with_demo=with_demo)
    for key, value in summary.items():
        click.echo(f"{key}: {value}")


@scarlet_cli.command("rotate-credentials")
def rotate_credentials() -> None:
    """Re-encrypt stored secrets with the current SCARLET_CREDENTIAL_ENCRYPTION_KEY."""
    from app.audit import audit
    from app.extensions import db
    from app.models import ConfigurationEntry, SSHKey, TargetCredential
    from app.security.crypto import get_cipher

    cipher = get_cipher()
    count = 0
    for cred in db.session.execute(db.select(TargetCredential)).scalars():
        cred.encrypted_secret = cipher.rotate(cred.encrypted_secret)
        if cred.encrypted_passphrase:
            cred.encrypted_passphrase = cipher.rotate(cred.encrypted_passphrase)
        cred.key_version += 1
        count += 1
    for key in db.session.execute(db.select(SSHKey)).scalars():
        key.encrypted_private_key = cipher.rotate(key.encrypted_private_key)
        if key.encrypted_passphrase:
            key.encrypted_passphrase = cipher.rotate(key.encrypted_passphrase)
        count += 1
    for entry in db.session.execute(
        db.select(ConfigurationEntry).where(ConfigurationEntry.encrypted_value.is_not(None))
    ).scalars():
        entry.encrypted_value = cipher.rotate(entry.encrypted_value)
        count += 1
    db.session.commit()
    audit.record(
        "ENCRYPTION_KEY_ROTATED",
        entity_type="System",
        details={"records": count, "key_id": cipher.key_id},
    )
    click.echo(
        f"Re-encrypted {count} secret record(s) with key {cipher.key_id}. You may now remove SCARLET_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS."
    )


@scarlet_cli.command("reconcile")
def reconcile() -> None:
    """Run reconciliation for all enabled hosts now (synchronously)."""
    from app.services.reconciliation_service import ReconciliationService

    click.echo(ReconciliationService().reconcile_all())


@scarlet_cli.command("cleanup")
def cleanup() -> None:
    """Run retention/cleanup policies now."""
    from app.services.cleanup_service import CleanupService

    click.echo(CleanupService().run_all())


@scarlet_cli.command("check-config")
def check_config() -> None:
    """Validate configuration and connectivity to database/redis."""
    from flask import current_app

    from app.api.health import _check_database, _check_redis

    click.echo(f"environment: {current_app.config['SCARLET_ENV']}")
    for name, (ok, message) in {"database": _check_database(), "redis": _check_redis()}.items():
        click.echo(f"{name}: {'OK' if ok else 'FAIL'} ({message})")


@scarlet_cli.command("validate-package")
@click.argument("path", type=click.Path(exists=True, dir_okay=False))
def validate_package(path: str) -> None:
    """Validate a .scarlet.tar.gz package without uploading it."""
    from flask import current_app

    from app.deployment.validator import build_validator_from_config

    report = build_validator_from_config(current_app.config).validate_file(
        path, os.path.basename(path)
    )
    click.echo(f"valid: {report.valid}")
    click.echo(f"sha256: {report.checksum_sha256}")
    if report.manifest:
        click.echo(
            f"application: {report.manifest.application} version: {report.manifest.version} runtime: {report.manifest.runtime}"
        )
    for err in report.errors:
        click.echo(f"ERROR: {err}", err=True)
    for warn in report.warnings:
        click.echo(f"WARNING: {warn}")
    sys.exit(0 if report.valid else 1)


@scarlet_cli.command("list-users")
def list_users() -> None:
    from app.repositories import UserRepository

    for user in UserRepository().all():
        click.echo(
            f"{user.id:4d} {user.username:20s} active={user.is_active} roles={','.join(user.role_names)}"
        )


def register_cli(app: Flask) -> None:
    app.cli.add_command(scarlet_cli)
