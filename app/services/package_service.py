"""Package upload, validation and release (creation of an immutable ApplicationVersion)."""

from __future__ import annotations

import json
import re
from typing import Any, BinaryIO

from flask import current_app

from app.audit import audit
from app.deployment.manifest import dump_manifest
from app.deployment.storage import get_artifact_storage
from app.deployment.validator import build_validator_from_config
from app.errors import (
    ConflictError,
    DuplicateReleaseError,
    NotFoundError,
    PackageValidationError,
    ValidationError,
)
from app.extensions import db
from app.models.application import ApplicationVersion, Package
from app.models.enums import AuditResult, PackageStatus
from app.repositories import ApplicationRepository, PackageRepository, VersionRepository
from app.security.validators import parse_semver
from app.utils.time import utcnow

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def sanitize_filename(name: str) -> str:
    name = (name or "package.tar.gz").replace("\\", "/").split("/")[-1]
    name = SAFE_FILENAME_RE.sub("_", name)[:200]
    return name or "package.tar.gz"


class PackageService:
    def __init__(self) -> None:
        self.packages = PackageRepository()
        self.apps = ApplicationRepository()
        self.versions = VersionRepository()

    def upload(
        self,
        stream: BinaryIO,
        original_filename: str,
        *,
        user=None,
        application_id: int | None = None,
        release_notes: str = "",
        auto_release: bool = True,
    ) -> Package:
        """Store, validate and (optionally) release an uploaded package.

        The bytes are streamed to the incoming area of the artifact storage,
        hashed on the fly, validated without extraction and then promoted to
        the immutable release location. Nothing is ever executed.
        """
        storage = get_artifact_storage()
        filename = sanitize_filename(original_filename)
        max_bytes = int(current_app.config.get("SCARLET_MAX_UPLOAD_MB", 2048)) * 1024 * 1024
        stored = storage.store_incoming(stream, max_bytes=max_bytes)
        package = Package(
            application_id=application_id,
            original_filename=filename,
            stored_filename=stored.storage_key.split("/")[-1],
            storage_key=stored.storage_key,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
            status=PackageStatus.VALIDATING.value,
            uploaded_by_id=getattr(user, "id", None),
        )
        db.session.add(package)
        db.session.commit()
        audit.record(
            "PACKAGE_UPLOADED",
            user=user,
            entity_type="Package",
            entity_id=package.id,
            details={
                "filename": filename,
                "size_bytes": stored.size_bytes,
                "checksum_sha256": stored.checksum_sha256,
            },
        )
        try:
            self.validate(package, expected_application_id=application_id)
            if package.status == PackageStatus.VALID.value and auto_release:
                self.release(package, user=user, release_notes=release_notes)
        except Exception:
            db.session.rollback()
            raise
        return package

    def validate(self, package: Package, *, expected_application_id: int | None = None) -> Package:
        storage = get_artifact_storage()
        validator = build_validator_from_config(current_app.config)
        local_path = storage.local_path(package.storage_key)
        report = validator.validate_file(local_path, package.original_filename)
        errors = list(report.errors)
        warnings = list(report.warnings)
        package.file_count = report.file_count
        package.scanner_result = report.scanner_result
        package.validated_at = utcnow()
        if report.manifest is not None:
            manifest = report.manifest
            package.manifest = manifest.to_dict()
            package.manifest_application = manifest.application
            package.manifest_version = manifest.version
            package.manifest_runtime = manifest.runtime_type
            app = self.apps.by_code(manifest.application)
            if app is None:
                errors.append(
                    f"Application '{manifest.application}' declared in the manifest is not registered in SCARLET."
                )
            else:
                if expected_application_id is not None and app.id != expected_application_id:
                    errors.append(
                        "The manifest application does not match the application selected for upload."
                    )
                if not app.enabled:
                    errors.append(f"Application '{app.code}' is disabled.")
                if not app.is_runtime_allowed(manifest.runtime_type):
                    errors.append(
                        f"Manifest runtime {manifest.runtime_type} is not allowed for application {app.code} ({app.runtime_type})."
                    )
                if manifest.hooks.all_scripts() and not app.allow_hooks:
                    errors.append(
                        "The manifest declares deployment hooks but hooks are not enabled for this application (allow_hooks)."
                    )
                existing = self.versions.by_app_and_version(app.id, manifest.version)
                if existing is not None:
                    if existing.checksum_sha256 == package.checksum_sha256:
                        errors.append(
                            f"Version {manifest.version} has already been released with an identical package."
                        )
                    else:
                        errors.append(
                            f"Version {manifest.version} already exists with a different checksum. Releases are immutable: publish a new version."
                        )
                package.application_id = app.id
            duplicate = self.versions.by_checksum(package.checksum_sha256)
            if duplicate is not None:
                errors.append(
                    f"An identical package was already released as {duplicate.application.code} {duplicate.version}."
                )
        package.validation_errors = errors
        package.validation_warnings = warnings
        package.status = PackageStatus.VALID.value if not errors else PackageStatus.INVALID.value
        if report.scanner_result == "INFECTED":
            package.status = PackageStatus.QUARANTINED.value
        db.session.commit()
        audit.record(
            "PACKAGE_VALIDATED",
            entity_type="Package",
            entity_id=package.id,
            application=package.application,
            result=(
                AuditResult.SUCCESS
                if package.status == PackageStatus.VALID.value
                else AuditResult.FAILURE
            ),
            details={
                "status": package.status,
                "errors": errors[:20],
                "warnings": warnings[:20],
                "manifest_application": package.manifest_application,
                "manifest_version": package.manifest_version,
            },
        )
        return package

    def release(
        self, package: Package, *, user=None, release_notes: str = ""
    ) -> ApplicationVersion:
        if package.status != PackageStatus.VALID.value:
            raise PackageValidationError(
                "Only VALID packages can be released.",
                errors={"package": package.validation_errors or []},
            )
        if package.version_id is not None:
            raise ConflictError("Package has already been released.")
        if package.application_id is None or not package.manifest:
            raise PackageValidationError("Package has no application/manifest information.")
        app = self.apps.get_or_404(package.application_id, "Application")
        manifest = package.manifest
        semver = parse_semver(manifest["version"])
        if self.versions.by_app_and_version(app.id, semver["version"]):
            raise DuplicateReleaseError()
        storage = get_artifact_storage()
        from app.deployment.manifest import Manifest

        manifest_yaml = dump_manifest(Manifest.model_validate(manifest))
        metadata = {
            "application": app.code,
            "version": semver["version"],
            "checksum_sha256": package.checksum_sha256,
            "size_bytes": package.size_bytes,
            "original_filename": package.original_filename,
            "uploaded_by": getattr(user, "username", None),
            "released_at": utcnow().isoformat(),
        }
        stored = storage.promote(
            package.storage_key, app.id, semver["version"], manifest_yaml, metadata
        )
        if stored.checksum_sha256 != package.checksum_sha256:
            raise PackageValidationError("Checksum changed during promotion; refusing to release.")
        image = manifest.get("image") or {}
        version = ApplicationVersion(
            application_id=app.id,
            version=semver["version"],
            major=semver["major"],
            minor=semver["minor"],
            patch=semver["patch"],
            prerelease=semver["prerelease"],
            build_metadata=semver["build_metadata"],
            runtime_type=str(manifest["runtime"]).upper(),
            image_name=image.get("name"),
            image_tag=image.get("tag"),
            manifest=manifest,
            checksum_sha256=package.checksum_sha256,
            release_notes=(release_notes or manifest.get("description") or "")[:4000],
            released_by_id=getattr(user, "id", None),
        )
        db.session.add(version)
        db.session.flush()
        package.version_id = version.id
        package.storage_key = stored.storage_key
        package.stored_filename = "package.tar.gz"
        db.session.commit()
        audit.record(
            "VERSION_RELEASED",
            user=user,
            application=app,
            entity_type="ApplicationVersion",
            entity_id=version.id,
            details={
                "version": version.version,
                "checksum_sha256": version.checksum_sha256,
                "runtime_type": version.runtime_type,
                "package_id": package.id,
            },
        )
        return version

    def delete_invalid(self, package: Package, *, user=None) -> None:
        if package.status == PackageStatus.VALID.value and package.version_id is not None:
            raise ConflictError("Released packages are immutable and cannot be deleted.")
        storage = get_artifact_storage()
        try:
            storage.delete(package.storage_key)
        except Exception:  # noqa: BLE001 - metadata cleanup must still happen
            pass
        db.session.delete(package)
        db.session.commit()
        audit.record(
            "PACKAGE_DELETED",
            user=user,
            entity_type="Package",
            entity_id=package.id,
            details={"filename": package.original_filename, "status": package.status},
        )

    def verify_integrity(self, version: ApplicationVersion) -> dict[str, Any]:
        """Re-hash the stored artifact and compare to the immutable checksum."""
        if version.package is None:
            raise NotFoundError("No package associated with this version.")
        storage = get_artifact_storage()
        actual = storage.checksum(version.package.storage_key)
        ok = actual == version.checksum_sha256
        if not ok:
            audit.security_event(
                "ARTIFACT_CHECKSUM_MISMATCH",
                f"Artifact for {version.application.code} {version.version} does not match its recorded checksum.",
                severity="CRITICAL",
                details={"expected": version.checksum_sha256, "actual": actual},
            )
        return {"ok": ok, "expected": version.checksum_sha256, "actual": actual}

    def manifest_json(self, version: ApplicationVersion) -> str:
        return json.dumps(version.manifest, indent=2)

    @staticmethod
    def validate_release_notes(text: str | None) -> str:
        text = (text or "").strip()
        if len(text) > 4000:
            raise ValidationError("Release notes too long (max 4000 characters).")
        return text
