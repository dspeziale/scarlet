"""Reusable column mixins."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column


class TenantMixin:
    """Adds tenant_id FK — every tenant-scoped table must include this."""

    tenant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
