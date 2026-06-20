"""IDS models: live alerts streamed from probes + per-tenant rule catalog."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


class IdsAlert(db.Model):
    """A single Suricata eve.json alert event reported by a probe."""

    __tablename__ = "ids_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False, index=True)

    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signature: Mapped[str | None] = mapped_column(String(512))
    category: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[int | None] = mapped_column(Integer)
    src_ip: Mapped[str | None] = mapped_column(String(45))
    src_port: Mapped[int | None] = mapped_column(Integer)
    dest_ip: Mapped[str | None] = mapped_column(String(45))
    dest_port: Mapped[int | None] = mapped_column(Integer)
    protocol: Mapped[str | None] = mapped_column(String(16))
    raw: Mapped[dict | None] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False, index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "probe_id": self.probe_id,
            "event_time": self.event_time.isoformat() if self.event_time else None,
            "signature": self.signature,
            "category": self.category,
            "severity": self.severity,
            "src_ip": self.src_ip,
            "src_port": self.src_port,
            "dest_ip": self.dest_ip,
            "dest_port": self.dest_port,
            "protocol": self.protocol,
            "received_at": self.received_at.isoformat(),
        }


class IdsRule(db.Model):
    """A Suricata rule in the tenant catalog. Can be assigned to probes."""

    __tablename__ = "ids_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    sid: Mapped[int | None] = mapped_column(Integer, index=True)
    msg: Mapped[str | None] = mapped_column(String(512))
    category: Mapped[str | None] = mapped_column(String(120))
    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "sid": self.sid,
            "msg": self.msg,
            "category": self.category,
            "rule_text": self.rule_text,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ProbeRuleAssignment(db.Model):
    """Which rules are active on which probe."""

    __tablename__ = "probe_rule_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(36), ForeignKey("ids_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    rule: Mapped["IdsRule"] = relationship("IdsRule")
