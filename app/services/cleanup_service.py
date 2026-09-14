"""Retention and cleanup policies.

Never deletes a release that is current or the rollback candidate (previous)
for any instance, and never purges audit records unless explicitly configured.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from flask import current_app

from app.audit import audit
from app.config.logging import get_logger
from app.deployment.remote_layout import RemoteLayout
from app.deployment.storage import get_artifact_storage
from app.errors import ScarletError
from app.extensions import db
from app.models import HealthCheck, OperationLog, Package
from app.models.audit import AuditLog
from app.models.enums import PackageStatus
from app.repositories import (
    ApplicationRepository,
    HostRepository,
    InstanceRepository,
    VersionRepository,
)
from app.services.settings_service import get_settings_service
from app.ssh.command import FileCommands
from app.ssh.factory import get_ssh_factory
from app.utils.time import utcnow

log = get_logger(__name__)


class CleanupService:
    def __init__(self) -> None:
        self.instances = InstanceRepository()
        self.versions = VersionRepository()
        self.apps = ApplicationRepository()
        self.hosts = HostRepository()

    def protected_version_ids(self) -> set[int]:
        protected: set[int] = set()
        for instance in self.instances.all():
            for vid in (
                instance.current_version_id,
                instance.previous_version_id,
                instance.desired_version_id,
            ):
                if vid:
                    protected.add(vid)
        return protected

    def run_all(self) -> dict[str, Any]:
        return {
            "incoming_packages": self.purge_incoming_packages(),
            "invalid_packages": self.purge_invalid_packages(),
            "health_checks": self.purge_health_checks(),
            "operation_logs": self.purge_operation_logs(),
            "audit": self.purge_audit(),
            "artifacts": self.purge_old_artifacts(),
        }

    def purge_incoming_packages(self, max_age_hours: int = 24) -> int:
        storage = get_artifact_storage()
        removed = 0
        cutoff = time.time() - max_age_hours * 3600
        for key, mtime in list(storage.iter_incoming()):
            if mtime < cutoff:
                in_use = db.session.execute(
                    db.select(Package.id).where(
                        Package.storage_key == key, Package.status == PackageStatus.VALID.value
                    )
                ).scalar_one_or_none()
                if in_use:
                    continue
                storage.delete(key)
                removed += 1
        return removed

    def purge_invalid_packages(self, max_age_days: int = 7) -> int:
        cutoff = utcnow() - timedelta(days=max_age_days)
        rows = list(
            db.session.execute(
                db.select(Package).where(
                    Package.status.in_(
                        [PackageStatus.INVALID.value, PackageStatus.QUARANTINED.value]
                    ),
                    Package.created_at < cutoff,
                )
            ).scalars()
        )
        storage = get_artifact_storage()
        for pkg in rows:
            try:
                storage.delete(pkg.storage_key)
            except ScarletError:
                pass
            db.session.delete(pkg)
        db.session.commit()
        return len(rows)

    def purge_health_checks(self) -> int:
        days = int(get_settings_service().get("SCARLET_LOG_RETENTION_DAYS", 90))
        cutoff = utcnow() - timedelta(days=days)
        result = db.session.execute(db.delete(HealthCheck).where(HealthCheck.checked_at < cutoff))
        db.session.commit()
        return result.rowcount or 0

    def purge_operation_logs(self) -> int:
        days = int(get_settings_service().get("SCARLET_OPERATION_LOG_RETENTION_DAYS", 180))
        cutoff = utcnow() - timedelta(days=days)
        result = db.session.execute(db.delete(OperationLog).where(OperationLog.timestamp < cutoff))
        db.session.commit()
        return result.rowcount or 0

    def purge_audit(self) -> int:
        days = int(current_app.config.get("SCARLET_AUDIT_RETENTION_DAYS", 0))
        if days <= 0:
            return 0
        cutoff = utcnow() - timedelta(days=days)
        count = db.session.execute(
            db.select(db.func.count(AuditLog.id)).where(AuditLog.timestamp < cutoff)
        ).scalar_one()
        if count:
            db.session.execute(db.delete(AuditLog).where(AuditLog.timestamp < cutoff))
            db.session.commit()
            audit.record(
                "AUDIT_PURGED",
                entity_type="AuditLog",
                details={"removed": count, "retention_days": days},
            )
        return count

    def purge_old_artifacts(self) -> int:
        """Deactivate and remove artifacts beyond the retention count per application."""
        keep = int(get_settings_service().get("SCARLET_ARTIFACT_RETENTION_COUNT", 10))
        protected = self.protected_version_ids()
        storage = get_artifact_storage()
        removed = 0
        for app in self.apps.all():
            versions = self.versions.for_application(app.id)  # newest first
            for version in versions[keep:]:
                if version.id in protected or version.package is None:
                    continue
                try:
                    storage.delete(version.package.storage_key)
                except ScarletError:
                    continue
                version.is_active = False
                removed += 1
                audit.record(
                    "ARTIFACT_PURGED",
                    application=app,
                    entity_type="ApplicationVersion",
                    entity_id=version.id,
                    details={"version": version.version},
                )
        db.session.commit()
        return removed

    def cleanup_remote_releases(self, host, application) -> dict[str, Any]:
        """Remove old release directories on a host, keeping current/previous and the newest N."""
        keep = int(get_settings_service().get("SCARLET_ARTIFACT_RETENTION_COUNT", 10))
        instance = self.instances.get_for(application.id, host.id)
        keep_versions = set()
        if instance is not None:
            for v in (
                instance.current_version,
                instance.previous_version,
                instance.desired_version,
            ):
                if v is not None:
                    keep_versions.add(v.version)
        if host.is_cluster_managed:
            # A cluster target keeps no release directory: nothing to prune on a filesystem.
            return {"removed": [], "kept": sorted(keep_versions), "skipped": "cluster target"}
        base = host.remote_base_path or current_app.config["SCARLET_REMOTE_BASE_PATH"]
        layout = RemoteLayout(base, application.code)
        fs = FileCommands(base)
        removed: list[str] = []
        with get_ssh_factory().connect(host) as client:
            listing = client.run(fs.list_dir(layout.releases_dir))
            if not listing.ok:
                return {"removed": [], "kept": sorted(keep_versions)}
            from app.security.validators import parse_semver

            releases = []
            for name in listing.stdout.split():
                try:
                    releases.append((parse_semver(name), name))
                except ScarletError:
                    continue
            releases.sort(key=lambda r: (r[0]["major"], r[0]["minor"], r[0]["patch"]), reverse=True)
            for index, (_, name) in enumerate(releases):
                if name in keep_versions or index < keep:
                    continue
                client.run(fs.remove_tree(layout.release_dir(name)))
                removed.append(name)
            # stale staging
            for name in client.run(fs.list_dir(layout.staging_dir)).stdout.split():
                client.run(
                    fs.remove_tree(f"{layout.staging_dir}/{name}")
                    if not name.endswith(".tar.gz")
                    else fs.remove_file(f"{layout.staging_dir}/{name}")
                )
        if removed:
            audit.record(
                "REMOTE_RELEASES_PURGED",
                application=application,
                target=host,
                entity_type="TargetHost",
                entity_id=host.id,
                details={"removed": removed},
            )
        return {"removed": removed, "kept": sorted(keep_versions)}
