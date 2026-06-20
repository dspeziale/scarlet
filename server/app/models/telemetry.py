"""Telemetry and accounting models."""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


def _now():
    return datetime.now(timezone.utc)


class DeviceInventory(db.Model):
    __tablename__ = "device_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False, index=True)
    mac: Mapped[str | None] = mapped_column(String(20), index=True)
    ip: Mapped[str | None] = mapped_column(String(45), index=True)
    hostname: Mapped[str | None] = mapped_column(String(255))
    vendor: Mapped[str | None] = mapped_column(String(120))
    device_type: Mapped[str | None] = mapped_column(String(60))
    os: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict | None] = mapped_column(JSON)  # full parsed scan info
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    probe: Mapped["Probe"] = relationship("Probe")  # type: ignore[name-defined]

    def to_dict(self, include_details: bool = False) -> dict:
        d = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "probe_id": self.probe_id,
            "mac": self.mac,
            "ip": self.ip,
            "hostname": self.hostname,
            "vendor": self.vendor,
            "device_type": self.device_type,
            "os": self.os,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
        }
        if include_details:
            d["details"] = self.details or {}
        return d


class DeviceSighting(db.Model):
    """One observation of a device — builds the intra-day presence history."""

    __tablename__ = "device_sightings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), ForeignKey("device_inventory.id", ondelete="CASCADE"), nullable=False, index=True)
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False, index=True)

    def to_dict(self) -> dict:
        return {"id": self.id, "device_id": self.device_id, "probe_id": self.probe_id,
                "seen_at": self.seen_at.isoformat()}


class ServiceInventory(db.Model):
    __tablename__ = "service_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False)
    device_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("device_inventory.id"))
    port: Mapped[int | None] = mapped_column(Integer)
    protocol: Mapped[str | None] = mapped_column(String(10))
    service: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[str | None] = mapped_column(String(80))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "probe_id": self.probe_id,
            "device_id": self.device_id,
            "port": self.port,
            "protocol": self.protocol,
            "service": self.service,
            "version": self.version,
        }


class WifiInventory(db.Model):
    __tablename__ = "wifi_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False)
    ssid: Mapped[str | None] = mapped_column(String(64))
    bssid: Mapped[str | None] = mapped_column(String(20))
    channel: Mapped[int | None] = mapped_column(Integer)
    encryption: Mapped[str | None] = mapped_column(String(60))
    signal: Mapped[int | None] = mapped_column(Integer)
    frequency: Mapped[int | None] = mapped_column(Integer)        # MHz
    vendor: Mapped[str | None] = mapped_column(String(120))       # OUI vendor
    standard: Mapped[str | None] = mapped_column(String(40))      # 802.11 a/b/g/n/ac/ax
    details: Mapped[dict | None] = mapped_column(JSON)            # everything else
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "probe_id": self.probe_id,
            "ssid": self.ssid,
            "bssid": self.bssid,
            "channel": self.channel,
            "encryption": self.encryption,
            "signal": self.signal,
            "frequency": self.frequency,
            "vendor": self.vendor,
            "standard": self.standard,
            "seen_at": self.seen_at.isoformat(),
            "details": self.details or {},
        }


class BLEInventory(db.Model):
    __tablename__ = "ble_inventory"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False)
    address: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(120))
    manufacturer: Mapped[str | None] = mapped_column(String(120))
    rssi: Mapped[int | None] = mapped_column(Integer)
    tx_power: Mapped[int | None] = mapped_column(Integer)
    appearance: Mapped[str | None] = mapped_column(String(60))
    device_class: Mapped[str | None] = mapped_column(String(40))
    paired: Mapped[bool | None] = mapped_column(Boolean)
    services: Mapped[list | None] = mapped_column(JSON)           # advertised UUIDs
    details: Mapped[dict | None] = mapped_column(JSON)            # everything else
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "probe_id": self.probe_id,
            "address": self.address,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "rssi": self.rssi,
            "tx_power": self.tx_power,
            "appearance": self.appearance,
            "device_class": self.device_class,
            "paired": self.paired,
            "services": self.services or [],
            "seen_at": self.seen_at.isoformat(),
            "details": self.details or {},
        }


class UsageAccounting(db.Model):
    __tablename__ = "usage_accounting"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    probe_id: Mapped[str] = mapped_column(String(36), ForeignKey("probes.id", ondelete="CASCADE"), nullable=False, index=True)
    period_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    cpu_seconds: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    memory_mb: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    network_in_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    network_out_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    disk_mb: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    probe: Mapped["Probe"] = relationship("Probe")  # type: ignore[name-defined]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "probe_id": self.probe_id,
            "period_date": self.period_date.isoformat(),
            "cpu_seconds": self.cpu_seconds,
            "memory_mb": self.memory_mb,
            "network_in_bytes": self.network_in_bytes,
            "network_out_bytes": self.network_out_bytes,
            "disk_mb": self.disk_mb,
            "task_count": self.task_count,
        }
