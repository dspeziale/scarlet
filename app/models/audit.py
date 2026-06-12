import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from app.core.db import db


class AuditLog(db.Model):
    """Append-only record of significant admin/security actions."""
    __tablename__ = 'audit_log'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ts = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    actor = Column(String, nullable=True)        # user email
    role = Column(String, nullable=True)
    action = Column(String, nullable=False)      # e.g. tenant.create, probe.command
    detail = Column(Text, nullable=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    ip = Column(String, nullable=True)

    @property
    def action_color(self):
        a = (self.action or '')
        if any(k in a for k in ('delete', 'reset', 'factory')):
            return 'danger'
        if any(k in a for k in ('command', 'push', 'rules', 'suricata')):
            return 'warning'
        if 'login' in a:
            return 'info'
        return 'secondary'
