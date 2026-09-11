"""Administrative system settings stored in the database."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PkMixin, TimestampMixin


class SystemSetting(PkMixin, TimestampMixin, Base):
    """Runtime-tunable setting. Never used for secrets (see SecretProvider)."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(8), default="str", nullable=False)  # str|int|bool
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="general", nullable=False)
    is_editable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def typed_value(self) -> Any:
        if self.value_type == "int":
            return int(self.value)
        if self.value_type == "bool":
            return self.value.strip().lower() in {"1", "true", "yes", "on"}
        return self.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.typed_value(),
            "value_type": self.value_type,
            "description": self.description,
            "category": self.category,
            "is_editable": self.is_editable,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
