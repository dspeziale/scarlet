import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.core.db import db

class Probe(db.Model):
    __tablename__ = 'probes'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    probe_name = Column(String, nullable=True)
    public_key = Column(String, nullable=False)
    shared_secret = Column(String, nullable=True)
    status = Column(String, nullable=False, default='pending') # pending | paired | revoked
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_seen = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    metadata_col = Column('metadata', JSONB, nullable=True) # JSONB for NeonDB/Postgres
    
    tenant_id = Column(UUID(as_uuid=True), ForeignKey('tenants.id'), nullable=True) # nullable for backwards compatibility during migration, but should be required
    license_code_id = Column(UUID(as_uuid=True), ForeignKey('license_codes.id'), nullable=True)
    
    tenant = relationship("Tenant", back_populates="probes")
    license = relationship("LicenseCode", back_populates="probe")
    devices = relationship("Device", back_populates="probe", cascade="all, delete-orphan")
    
    # Internal fields for handshake
    server_private_key = Column(String, nullable=True) # Ephemeral server key for this probe
    challenge = Column(String, nullable=True)

    # Runtime info reported by the probe via heartbeat:
    # {"interfaces": ["eth0", ...], "suricata": {"running": bool, "interface": str, "installed": bool}}
    runtime_info = Column(JSONB, nullable=True)
    
    tasks = relationship("Task", back_populates="probe", cascade="all, delete-orphan")

class Task(db.Model):
    __tablename__ = 'tasks'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    probe_id = Column(UUID(as_uuid=True), ForeignKey('probes.id'), nullable=False)
    
    action = Column(String, nullable=False) # command type, e.g. "vuln_scan", "suricata_start"
    target_ip = Column(String, nullable=True) # legacy single-arg; new commands use params
    params = Column(JSONB, nullable=True)     # structured command parameters
    status = Column(String, nullable=False, default='pending') # pending, running, completed, failed
    result = Column(JSONB, nullable=True)

    issued_by = Column(String, nullable=True) # email of the admin who issued the command
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    
    probe = relationship("Probe", back_populates="tasks")
