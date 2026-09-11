"""Applications, versions, packages, target rules and application instances.

``ApplicationInstance`` is the control-plane record for one application on one
target: it stores the DESIRED state (what the operator asked for) and the
ACTUAL state (what the reconciler last observed on the host). Drift is the
difference between the two.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin, TimestampMixin
from app.models.enums import (
    ApplicationState,
    DesiredState,
    DriftType,
    HealthCheckType,
    HealthStatus,
    PackageStatus,
)


class Application(PkMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    owner: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    repository: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    artifact_type: Mapped[str] = mapped_column(
        String(32), default="container-image", nullable=False
    )
    runtime_type: Mapped[str] = mapped_column(String(16), nullable=False)
    default_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    healthcheck_type: Mapped[str] = mapped_column(
        String(24), default=HealthCheckType.CONTAINER_STATUS.value, nullable=False
    )
    healthcheck_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    healthcheck_command: Mapped[str | None] = mapped_column(String(512), nullable=True)
    healthcheck_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    healthcheck_expected_status: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    healthcheck_timeout: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    healthcheck_retries: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    healthcheck_interval: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_hooks: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # target rules (allowlists). Empty list means "any".
    allowed_environments: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    allowed_runtimes: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    allowed_host_group_ids: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)

    versions: Mapped[list[ApplicationVersion]] = relationship(
        back_populates="application", cascade="all, delete-orphan", order_by="ApplicationVersion.id"
    )
    instances: Mapped[list[ApplicationInstance]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )

    def is_environment_allowed(self, env_code: str) -> bool:
        return not self.allowed_environments or env_code in self.allowed_environments

    def is_runtime_allowed(self, runtime: str) -> bool:
        return runtime == self.runtime_type or (
            bool(self.allowed_runtimes) and runtime in self.allowed_runtimes
        )

    def is_host_group_allowed(self, group_ids: list[int]) -> bool:
        if not self.allowed_host_group_ids:
            return True
        return any(gid in self.allowed_host_group_ids for gid in group_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "description": self.description,
            "owner": self.owner,
            "repository": self.repository,
            "artifact_type": self.artifact_type,
            "runtime_type": self.runtime_type,
            "default_port": self.default_port,
            "healthcheck": {
                "type": self.healthcheck_type,
                "url": self.healthcheck_url,
                "command": self.healthcheck_command,
                "port": self.healthcheck_port,
                "expected_status": self.healthcheck_expected_status,
                "timeout": self.healthcheck_timeout,
                "retries": self.healthcheck_retries,
                "interval": self.healthcheck_interval,
            },
            "enabled": self.enabled,
            "allow_hooks": self.allow_hooks,
            "allowed_environments": list(self.allowed_environments or []),
            "allowed_runtimes": list(self.allowed_runtimes or []),
            "allowed_host_group_ids": list(self.allowed_host_group_ids or []),
            "version_count": len(self.versions),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ApplicationVersion(PkMixin, TimestampMixin, Base):
    """Immutable released version of an application."""

    __tablename__ = "application_versions"
    __table_args__ = (
        UniqueConstraint("application_id", "version", name="uq_application_versions_app_version"),
        Index("ix_application_versions_application_id", "application_id"),
    )

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    major: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    patch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prerelease: Mapped[str | None] = mapped_column(String(64), nullable=True)
    build_metadata: Mapped[str | None] = mapped_column(String(64), nullable=True)
    runtime_type: Mapped[str] = mapped_column(String(16), nullable=False)
    image_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_tag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    release_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    released_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    application: Mapped[Application] = relationship(back_populates="versions")
    package: Mapped[Package | None] = relationship(back_populates="version", uselist=False)

    @property
    def sort_key(self) -> tuple:
        return (self.major, self.minor, self.patch, self.prerelease is None, self.prerelease or "")

    def to_dict(self, include_manifest: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "application_id": self.application_id,
            "application_code": self.application.code if self.application else None,
            "version": self.version,
            "major": self.major,
            "minor": self.minor,
            "patch": self.patch,
            "prerelease": self.prerelease,
            "build_metadata": self.build_metadata,
            "runtime_type": self.runtime_type,
            "image_name": self.image_name,
            "image_tag": self.image_tag,
            "checksum_sha256": self.checksum_sha256,
            "release_notes": self.release_notes,
            "is_active": self.is_active,
            "package_id": self.package.id if self.package else None,
            "package_status": self.package.status if self.package else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_manifest:
            data["manifest"] = self.manifest
        return data


class Package(PkMixin, TimestampMixin, Base):
    """Uploaded release package (metadata only; bytes live in ArtifactStorage)."""

    __tablename__ = "packages"

    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_versions.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=PackageStatus.UPLOADED.value, nullable=False, index=True
    )
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    manifest_application: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifest_runtime: Mapped[str | None] = mapped_column(String(16), nullable=True)
    validation_errors: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    validation_warnings: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scanner_result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    file_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    application: Mapped[Application | None] = relationship()
    version: Mapped[ApplicationVersion | None] = relationship(back_populates="package")
    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "application_id": self.application_id,
            "application_code": self.application.code if self.application else None,
            "version_id": self.version_id,
            "original_filename": self.original_filename,
            "size_bytes": self.size_bytes,
            "checksum_sha256": self.checksum_sha256,
            "status": self.status,
            "manifest_application": self.manifest_application,
            "manifest_version": self.manifest_version,
            "manifest_runtime": self.manifest_runtime,
            "validation_errors": self.validation_errors or [],
            "validation_warnings": self.validation_warnings or [],
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "scanner_result": self.scanner_result,
            "file_count": self.file_count,
            "uploaded_by": self.uploaded_by.username if self.uploaded_by else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ApplicationInstance(PkMixin, TimestampMixin, Base):
    """Control-plane record: desired vs actual state of an application on a target."""

    __tablename__ = "application_instances"
    __table_args__ = (
        UniqueConstraint("application_id", "host_id", name="uq_app_instances_app_host"),
        Index("ix_app_instances_actual_state", "actual_state"),
    )

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    host_id: Mapped[int] = mapped_column(
        ForeignKey("target_hosts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ---- DESIRED state (set by operators through deployments/lifecycle ops)
    desired_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_versions.id", ondelete="SET NULL"), nullable=True
    )
    desired_state: Mapped[str] = mapped_column(
        String(16), default=DesiredState.RUNNING.value, nullable=False
    )
    desired_replicas: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    desired_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    desired_updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # ---- ACTUAL state (observed on the host)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_versions.id", ondelete="SET NULL"), nullable=True
    )
    previous_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("application_versions.id", ondelete="SET NULL"), nullable=True
    )
    actual_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actual_state: Mapped[str] = mapped_column(
        String(16), default=ApplicationState.UNKNOWN.value, nullable=False
    )
    actual_replicas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_runtime: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actual_observed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    health_status: Mapped[str] = mapped_column(
        String(16), default=HealthStatus.UNKNOWN.value, nullable=False
    )
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_health_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    drift_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    drift_type: Mapped[str] = mapped_column(
        String(24), default=DriftType.NONE.value, nullable=False
    )
    drift_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    drift_detected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    last_deployment_id: Mapped[int | None] = mapped_column(
        ForeignKey("deployments.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    last_operation_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    application: Mapped[Application] = relationship(back_populates="instances")
    host = relationship("TargetHost")
    desired_version: Mapped[ApplicationVersion | None] = relationship(
        foreign_keys=[desired_version_id]
    )
    current_version: Mapped[ApplicationVersion | None] = relationship(
        foreign_keys=[current_version_id]
    )
    previous_version: Mapped[ApplicationVersion | None] = relationship(
        foreign_keys=[previous_version_id]
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "application_id": self.application_id,
            "application_code": self.application.code if self.application else None,
            "application_name": self.application.name if self.application else None,
            "host_id": self.host_id,
            "host_name": self.host.name if self.host else None,
            "environment": (
                self.host.environment.code if self.host and self.host.environment else None
            ),
            "is_production": self.host.is_production if self.host else False,
            "runtime_type": self.host.runtime_type if self.host else None,
            "desired": {
                "version": self.desired_version.version if self.desired_version else None,
                "version_id": self.desired_version_id,
                "state": self.desired_state,
                "replicas": self.desired_replicas,
                "updated_at": (
                    self.desired_updated_at.isoformat() if self.desired_updated_at else None
                ),
            },
            "actual": {
                "version": self.actual_version
                or (self.current_version.version if self.current_version else None),
                "version_id": self.current_version_id,
                "state": self.actual_state,
                "replicas": self.actual_replicas,
                "runtime": self.actual_runtime,
                "observed_at": (
                    self.actual_observed_at.isoformat() if self.actual_observed_at else None
                ),
                "details": self.actual_details or {},
            },
            "current_version": self.current_version.version if self.current_version else None,
            "previous_version": self.previous_version.version if self.previous_version else None,
            "state": self.actual_state,
            "health_status": self.health_status,
            "last_health_check_at": (
                self.last_health_check_at.isoformat() if self.last_health_check_at else None
            ),
            "last_health_message": self.last_health_message,
            "drift_detected": self.drift_detected,
            "drift_type": self.drift_type,
            "drift_details": self.drift_details or {},
            "last_deployment_id": self.last_deployment_id,
            "last_operation_at": (
                self.last_operation_at.isoformat() if self.last_operation_at else None
            ),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
