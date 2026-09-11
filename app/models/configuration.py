"""Per-application, per-environment configuration with versioning and encrypted secrets."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, PkMixin, TimestampMixin
from app.models.enums import ConfigValueType


class Configuration(PkMixin, TimestampMixin, Base):
    """Configuration set for an application in one environment."""

    __tablename__ = "configurations"
    __table_args__ = (
        UniqueConstraint("application_id", "environment_id", name="uq_configurations_app_env"),
    )

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environments.id", ondelete="CASCADE"), nullable=False
    )
    current_version_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    application = relationship("Application")
    environment = relationship("Environment")
    entries: Mapped[list[ConfigurationEntry]] = relationship(
        back_populates="configuration", cascade="all, delete-orphan", order_by="ConfigurationEntry.key"
    )
    versions: Mapped[list[ConfigurationVersion]] = relationship(
        back_populates="configuration",
        cascade="all, delete-orphan",
        order_by="ConfigurationVersion.version_number.desc()",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "application_id": self.application_id,
            "application_code": self.application.code if self.application else None,
            "environment": self.environment.code if self.environment else None,
            "environment_id": self.environment_id,
            "current_version_number": self.current_version_number,
            "description": self.description,
            "entries": [e.to_dict() for e in self.entries],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ConfigurationEntry(PkMixin, TimestampMixin, Base):
    """One key. Secrets are stored encrypted and never returned once written."""

    __tablename__ = "configuration_entries"
    __table_args__ = (UniqueConstraint("configuration_id", "key", name="uq_config_entries_key"),)

    configuration_id: Mapped[int] = mapped_column(
        ForeignKey("configurations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_type: Mapped[str] = mapped_column(
        String(8), default=ConfigValueType.CONFIG.value, nullable=False
    )
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    configuration: Mapped[Configuration] = relationship(back_populates="entries")

    @property
    def is_secret(self) -> bool:
        return self.value_type == ConfigValueType.SECRET.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "value_type": self.value_type,
            # secrets are masked; the API never returns the plaintext
            "value": "********" if self.is_secret else self.value,
            "is_secret": self.is_secret,
            "description": self.description,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ConfigurationVersion(PkMixin, Base):
    """Immutable snapshot of a configuration (secret values are hashed, not stored)."""

    __tablename__ = "configuration_versions"
    __table_args__ = (
        UniqueConstraint("configuration_id", "version_number", name="uq_config_versions_number"),
    )

    configuration_id: Mapped[int] = mapped_column(
        ForeignKey("configurations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    change_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # {key: {"type": "CONFIG", "value": "..."} | {"type": "SECRET", "sha256": "..."}}
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    configuration: Mapped[Configuration] = relationship(back_populates="versions")
    created_by = relationship("User")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version_number": self.version_number,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by.username if self.created_by else None,
            "change_summary": self.change_summary,
            "keys": sorted(self.snapshot.keys()),
            "is_current": self.is_current,
        }
