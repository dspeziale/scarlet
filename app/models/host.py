"""Environments, target hosts, host groups, credentials and SSH keys."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin, TimestampMixin
from app.models.enums import CredentialType, HostKeyStatus, HostStatus, RuntimeType


class Environment(PkMixin, TimestampMixin, Base):
    __tablename__ = "environments"

    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    is_production: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="secondary", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    require_confirmation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    allow_rollback: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_parallel_deployments: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    hosts: Mapped[list[TargetHost]] = relationship(back_populates="environment")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "name": self.name,
            "description": self.description,
            "is_production": self.is_production,
            "color": self.color,
            "require_confirmation": self.require_confirmation,
            "require_approval": self.require_approval,
            "allow_rollback": self.allow_rollback,
            "max_parallel_deployments": self.max_parallel_deployments,
        }


class HostGroup(PkMixin, TimestampMixin, Base):
    __tablename__ = "host_groups"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    environment_id: Mapped[int | None] = mapped_column(
        ForeignKey("environments.id", ondelete="SET NULL"), nullable=True
    )

    environment: Mapped[Environment | None] = relationship()
    hosts: Mapped[list[TargetHost]] = relationship(
        secondary="host_group_members", back_populates="groups"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "environment": self.environment.code if self.environment else None,
            "host_ids": [h.id for h in self.hosts],
            "host_count": len(self.hosts),
        }


class HostGroupMember(Base):
    __tablename__ = "host_group_members"

    host_group_id: Mapped[int] = mapped_column(
        ForeignKey("host_groups.id", ondelete="CASCADE"), primary_key=True
    )
    host_id: Mapped[int] = mapped_column(
        ForeignKey("target_hosts.id", ondelete="CASCADE"), primary_key=True
    )


class TargetHost(PkMixin, TimestampMixin, Base):
    __tablename__ = "target_hosts"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    ssh_port: Mapped[int] = mapped_column(Integer, default=22, nullable=False)
    ssh_username: Mapped[str] = mapped_column(String(32), nullable=False)
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # discovered system information (read-only, never trusted for command building)
    os_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    architecture: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kernel_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cpu_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_total_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_available_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_total_mb: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_available_mb: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    runtime_type: Mapped[str] = mapped_column(
        String(16), default=RuntimeType.NONE.value, nullable=False
    )
    runtime_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    runtime_rootless: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    kubernetes_context: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kubernetes_namespace: Mapped[str | None] = mapped_column(String(63), nullable=True)
    kubernetes_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_base_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ssh host key management
    ssh_host_key_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ssh_host_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ssh_host_key_status: Mapped[str] = mapped_column(
        String(24), default=HostKeyStatus.UNKNOWN.value, nullable=False
    )
    ssh_host_key_approved_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ssh_host_key_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ssh_pending_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ssh_pending_host_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_pending_host_key_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    status: Mapped[str] = mapped_column(
        String(16), default=HostStatus.UNKNOWN.value, nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_discovery_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    discovery_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    environment: Mapped[Environment] = relationship(back_populates="hosts")
    groups: Mapped[list[HostGroup]] = relationship(
        secondary="host_group_members", back_populates="hosts"
    )
    credentials: Mapped[list[TargetCredential]] = relationship(
        back_populates="host", cascade="all, delete-orphan"
    )
    capabilities: Mapped[list[RuntimeCapability]] = relationship(
        back_populates="host", cascade="all, delete-orphan"
    )

    @property
    def is_production(self) -> bool:
        return bool(self.environment and self.environment.is_production)

    @property
    def active_credential(self) -> TargetCredential | None:
        for cred in self.credentials:
            if cred.is_active and cred.credential_type in {
                CredentialType.PASSWORD.value,
                CredentialType.PRIVATE_KEY.value,
            }:
                return cred
        return None

    @property
    def kubernetes_credential(self) -> TargetCredential | None:
        for cred in self.credentials:
            if cred.is_active and cred.credential_type in {
                CredentialType.KUBECONFIG.value,
                CredentialType.K8S_TOKEN.value,
            }:
                return cred
        return None

    @property
    def is_cluster_managed(self) -> bool:
        """True when SCARLET reaches this target through the Kubernetes API only.

        A cluster target has no shell: there is no SSH credential to use, no release
        directory to write and no host key to approve. Everything happens through the
        cluster API with the stored kubeconfig.
        """
        return (
            self.runtime_type == RuntimeType.KUBERNETES.value
            and self.kubernetes_credential is not None
        )

    @property
    def access_mode(self) -> str:
        """How SCARLET reaches the target: ``API`` for a cluster, ``SSH`` otherwise."""
        return "API" if self.is_cluster_managed else "SSH"

    @property
    def address(self) -> str:
        return self.ip_address or self.hostname

    @property
    def effective_status(self) -> str:
        if not self.enabled:
            return HostStatus.DISABLED.value
        return self.status

    def to_dict(self, include_system: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "hostname": self.hostname,
            "ip_address": self.ip_address,
            "ssh_port": self.ssh_port,
            "ssh_username": self.ssh_username,
            "environment": self.environment.code if self.environment else None,
            "environment_id": self.environment_id,
            "is_production": self.is_production,
            "enabled": self.enabled,
            "description": self.description,
            "runtime_type": self.runtime_type,
            "runtime_version": self.runtime_version,
            "runtime_rootless": self.runtime_rootless,
            "kubernetes_context": self.kubernetes_context,
            "kubernetes_namespace": self.kubernetes_namespace,
            "access_mode": self.access_mode,
            "kubernetes_version": self.kubernetes_version,
            "status": self.effective_status,
            "ssh_fingerprint": self.ssh_fingerprint,
            "ssh_host_key_type": self.ssh_host_key_type,
            "ssh_host_key_status": self.ssh_host_key_status,
            "ssh_pending_fingerprint": self.ssh_pending_fingerprint,
            "has_credential": self.active_credential is not None,
            "credential_type": (
                self.active_credential.credential_type if self.active_credential else None
            ),
            "groups": [g.name for g in self.groups],
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "last_health_check_at": (
                self.last_health_check_at.isoformat() if self.last_health_check_at else None
            ),
            "last_discovery_at": (
                self.last_discovery_at.isoformat() if self.last_discovery_at else None
            ),
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_system:
            data["system"] = {
                "os_name": self.os_name,
                "os_version": self.os_version,
                "architecture": self.architecture,
                "kernel_version": self.kernel_version,
                "cpu_count": self.cpu_count,
                "memory_total_mb": self.memory_total_mb,
                "memory_available_mb": self.memory_available_mb,
                "disk_total_mb": self.disk_total_mb,
                "disk_available_mb": self.disk_available_mb,
            }
        return data


class TargetCredential(PkMixin, TimestampMixin, Base):
    """Encrypted SSH / Kubernetes credential for a target host.

    ``encrypted_secret`` holds the Fernet ciphertext of the password, private key
    or kubeconfig. ``encrypted_passphrase`` holds the ciphertext of the key
    passphrase. Neither is ever serialized.
    """

    __tablename__ = "target_credentials"

    host_id: Mapped[int] = mapped_column(
        ForeignKey("target_hosts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), default="default", nullable=False)
    credential_type: Mapped[str] = mapped_column(String(16), nullable=False)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_passphrase: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    key_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    host: Mapped[TargetHost] = relationship(back_populates="credentials")

    def to_dict(self) -> dict[str, Any]:
        """Metadata only. Secret material is never exposed."""
        return {
            "id": self.id,
            "host_id": self.host_id,
            "name": self.name,
            "credential_type": self.credential_type,
            "username": self.username,
            "key_fingerprint": self.key_fingerprint,
            "key_type": self.key_type,
            "is_active": self.is_active,
            "rotated_at": self.rotated_at.isoformat() if self.rotated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<TargetCredential id={self.id} host={self.host_id} type={self.credential_type}>"


class SSHKey(PkMixin, TimestampMixin, Base):
    """SCARLET-owned SSH keypair that can be reused across hosts.

    The private key is encrypted at rest; only the public key is exposed so
    administrators can install it on target hosts.
    """

    __tablename__ = "ssh_keys"

    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    key_type: Mapped[str] = mapped_column(String(32), nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_private_key: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_passphrase: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    comment: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "key_type": self.key_type,
            "public_key": self.public_key,
            "fingerprint": self.fingerprint,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RuntimeCapability(PkMixin, TimestampMixin, Base):
    """Capability discovered on a host (e.g. podman 4.9 rootless, kubectl 1.30)."""

    __tablename__ = "runtime_capabilities"
    __table_args__ = (
        UniqueConstraint("host_id", "runtime_type", name="uq_runtime_cap_host_runtime"),
    )

    host_id: Mapped[int] = mapped_column(
        ForeignKey("target_hosts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    runtime_type: Mapped[str] = mapped_column(String(16), nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rootless: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    binary_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    host: Mapped[TargetHost] = relationship(back_populates="capabilities")

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime_type": self.runtime_type,
            "available": self.available,
            "version": self.version,
            "rootless": self.rootless,
            "binary_path": self.binary_path,
            "details": self.details or {},
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }
