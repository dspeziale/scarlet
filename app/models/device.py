import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.db import db

class Device(db.Model):
    __tablename__ = 'devices'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id'), nullable=False)
    probe_id = Column(UUID(as_uuid=True), ForeignKey('probes.id'), nullable=False)
    
    ip_address = Column(String, nullable=False)
    mac_address = Column(String, nullable=True)
    os_info = Column(String, nullable=True)
    hostname = Column(String, nullable=True)
    snmp_sys_descr = Column(String, nullable=True)
    
    first_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    vulnerabilities = Column(JSONB, nullable=True)

    tenant = relationship("Tenant", back_populates="devices")
    probe = relationship("Probe", back_populates="devices")
    services = relationship("DeviceService", back_populates="device", cascade="all, delete-orphan")

class DeviceService(db.Model):
    __tablename__ = 'device_services'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey('devices.id'), nullable=False)
    
    port = Column(Integer, nullable=False)
    protocol = Column(String, nullable=False) # tcp, udp
    state = Column(String, nullable=True)     # open, closed, filtered
    service_name = Column(String, nullable=True)
    service_version = Column(String, nullable=True)
    
    last_checked = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    device = relationship("Device", back_populates="services")
