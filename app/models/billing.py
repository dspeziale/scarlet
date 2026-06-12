import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Float
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import db


class TenantBilling(db.Model):
    """Per-tenant billing plan: a fixed recurring fee plus metered pay-per-use prices."""
    __tablename__ = 'tenant_billing'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id'), nullable=False, unique=True)

    currency = Column(String, nullable=False, default='EUR')
    fixed_fee = Column(Float, nullable=False, default=0.0)        # recurring base fee
    price_per_probe = Column(Float, nullable=False, default=0.0)  # per active probe
    price_per_asset = Column(Float, nullable=False, default=0.0)  # per discovered device
    price_per_scan = Column(Float, nullable=False, default=0.0)   # per vulnerability scan
    price_per_alert = Column(Float, nullable=False, default=0.0)  # per IDS alert
    price_per_ai = Column(Float, nullable=False, default=0.0)     # per AI analysis (reserved)
    price_per_gb = Column(Float, nullable=False, default=0.0)         # per GB ingested (bandwidth)
    price_per_notification = Column(Float, nullable=False, default=0.0)  # per Telegram/email sent
    price_per_cpu_min = Column(Float, nullable=False, default=0.0)    # per probe CPU-minute

    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    @classmethod
    def for_tenant(cls, tenant_id):
        return cls.query.filter_by(tenant_id=tenant_id).first()


class TenantUsage(db.Model):
    """Cumulative metered usage per tenant, fed by ingest/notify/heartbeat paths."""
    __tablename__ = 'tenant_usage'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id'), nullable=False, unique=True)
    bytes_in = Column(Float, nullable=False, default=0.0)         # bytes received from probes
    notifications = Column(Float, nullable=False, default=0.0)    # notifications sent
    cpu_seconds = Column(Float, nullable=False, default=0.0)      # accumulated probe CPU-seconds
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    @classmethod
    def add(cls, tenant_id, *, bytes_in=0.0, notifications=0.0, cpu_seconds=0.0):
        """Atomically increments counters for a tenant (best-effort)."""
        if not tenant_id:
            return
        try:
            row = cls.query.filter_by(tenant_id=tenant_id).first()
            if not row:
                row = cls(tenant_id=tenant_id)
                db.session.add(row)
            row.bytes_in = (row.bytes_in or 0) + bytes_in
            row.notifications = (row.notifications or 0) + notifications
            row.cpu_seconds = (row.cpu_seconds or 0) + cpu_seconds
            db.session.commit()
        except Exception:
            db.session.rollback()
