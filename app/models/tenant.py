import uuid
import secrets
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.db import db

class Tenant(db.Model):
    __tablename__ = 'tenants'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    licenses = relationship("LicenseCode", back_populates="tenant", cascade="all, delete-orphan")
    probes = relationship("Probe", back_populates="tenant")
    devices = relationship("Device", back_populates="tenant")

class LicenseCode(db.Model):
    __tablename__ = 'license_codes'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id'), nullable=False)
    code = Column(String, nullable=False, unique=True, default=lambda: secrets.token_hex(8).upper())
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    used_at = Column(DateTime(timezone=True), nullable=True)

    tenant = relationship("Tenant", back_populates="licenses")
    probe = relationship("Probe", back_populates="license", uselist=False)
