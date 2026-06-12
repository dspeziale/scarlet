import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.core.db import db


class IdsRuleset(db.Model):
    """A centrally-managed Suricata ruleset, downloaded from the internet and
    distributed to every probe. A single active row is kept and replaced on update."""
    __tablename__ = 'ids_ruleset'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_url = Column(String, nullable=True)
    version = Column(String, nullable=True)        # short sha256 of the rules text
    rule_count = Column(Integer, nullable=True)
    rules_text = Column(Text, nullable=True)        # the full concatenated .rules content
    # [{"name": "Scan", "count": 1234, "enabled": true}, ...] — which categories ship to probes
    categories = Column(JSONB, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    @classmethod
    def current(cls):
        return cls.query.order_by(cls.updated_at.desc()).first()
