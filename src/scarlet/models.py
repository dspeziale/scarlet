"""Modello dati: applicazioni e deployment registrati."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    repository: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deployments: Mapped[list[Deployment]] = relationship(back_populates="application")


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (
        Index("ix_deployments_app_env_time", "application_id", "environment", "deployed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    commit: Mapped[str | None] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    application: Mapped[Application] = relationship(back_populates="deployments")
