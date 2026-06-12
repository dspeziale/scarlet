import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Float
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.db import db


class WifiNetwork(db.Model):
    """A nearby WiFi access point discovered by a probe (deduplicated by BSSID)."""
    __tablename__ = 'wifi_networks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id'), nullable=True)
    probe_id = Column(UUID(as_uuid=True), ForeignKey('probes.id'), nullable=False)

    bssid = Column(String, nullable=False)
    ssid = Column(String, nullable=True)
    channel = Column(Integer, nullable=True)
    signal = Column(Float, nullable=True)        # dBm
    encryption = Column(String, nullable=True)

    first_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    probe = relationship("Probe")

    @property
    def signal_color(self):
        if self.signal is None:
            return "secondary"
        if self.signal >= -55:
            return "success"
        if self.signal >= -70:
            return "warning"
        return "danger"


class BleDevice(db.Model):
    """A nearby Bluetooth Low Energy device discovered by a probe (dedup by address)."""
    __tablename__ = 'ble_devices'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id'), nullable=True)
    probe_id = Column(UUID(as_uuid=True), ForeignKey('probes.id'), nullable=False)

    address = Column(String, nullable=False)
    name = Column(String, nullable=True)
    rssi = Column(Integer, nullable=True)

    first_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    probe = relationship("Probe")
