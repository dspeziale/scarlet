import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.core.db import db


class SuricataEvent(db.Model):
    __tablename__ = 'suricata_events'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    probe_id = Column(UUID(as_uuid=True), ForeignKey('probes.id'), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id'), nullable=True)

    event_ts = Column(String, nullable=True)        # original Suricata timestamp
    event_type = Column(String, nullable=True)      # alert | flow | http | dns | tls | stats
    severity = Column(Integer, nullable=True)
    signature = Column(String, nullable=True)
    signature_id = Column(String, nullable=True)
    category = Column(String, nullable=True)
    src_ip = Column(String, nullable=True)
    dest_ip = Column(String, nullable=True)
    proto = Column(String, nullable=True)
    line = Column(String, nullable=True)             # pre-formatted terminal line
    raw = Column(JSONB, nullable=True)

    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    @property
    def severity_color(self):
        try:
            s = int(self.severity)
        except (TypeError, ValueError):
            return "secondary"
        if s <= 1:
            return "danger"
        if s == 2:
            return "warning"
        return "info"
