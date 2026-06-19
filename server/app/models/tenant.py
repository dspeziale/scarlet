"""Tenant model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


class Tenant(db.Model):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(60), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(String(30), nullable=False, default="free")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_probes: Mapped[int] = mapped_column(default=5, nullable=False)

    # Per-tenant notification settings (Telegram bot + Gmail SMTP).
    notify_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    telegram_bot_token: Mapped[str | None] = mapped_column(String(120))
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))   # default chat
    gmail_address: Mapped[str | None] = mapped_column(String(255))
    gmail_app_password: Mapped[str | None] = mapped_column(String(255))
    notify_email: Mapped[str | None] = mapped_column(String(255))      # default recipient

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # relationships
    users: Mapped[list] = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    probes: Mapped[list] = relationship("Probe", back_populates="tenant", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "plan": self.plan,
            "is_active": self.is_active,
            "max_probes": self.max_probes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "notify_enabled": self.notify_enabled,
        }

    def notification_settings_dict(self) -> dict:
        """Notification config with secrets masked (never expose token/password)."""
        return {
            "notify_enabled": self.notify_enabled,
            "telegram_bot_token_set": bool(self.telegram_bot_token),
            "telegram_chat_id": self.telegram_chat_id,
            "gmail_address": self.gmail_address,
            "gmail_app_password_set": bool(self.gmail_app_password),
            "notify_email": self.notify_email,
        }
