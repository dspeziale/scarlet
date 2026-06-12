from uuid import UUID
from datetime import datetime, timezone
from app.core.db import db
from app.models.probe import Probe

class ProbeService:
    @staticmethod
    def create_probe(probe_name: str, public_key: str, server_private_key: str, challenge: str, tenant_id: str, license_code_id: str, metadata: dict = None) -> Probe:
        probe = Probe(
            probe_name=probe_name,
            public_key=public_key,
            server_private_key=server_private_key,
            challenge=challenge,
            tenant_id=tenant_id,
            license_code_id=license_code_id,
            status='pending',
            metadata_col=metadata
        )
        db.session.add(probe)
        db.session.commit()
        return probe
    
    @staticmethod
    def get_probe_by_id(probe_id: str) -> Probe:
        try:
            uuid_obj = UUID(probe_id)
        except ValueError:
            return None
        return db.session.get(Probe, uuid_obj)
        
    @staticmethod
    def update_probe_status(probe: Probe, status: str, shared_secret: str = None) -> None:
        probe.status = status
        if shared_secret:
            probe.shared_secret = shared_secret
        
        # Once paired, we can optionally delete the ephemeral server private key from db
        if status == 'paired':
            probe.server_private_key = None
            probe.challenge = None
            
        db.session.commit()
        
    @staticmethod
    def update_last_seen(probe: Probe) -> None:
        probe.last_seen = datetime.now(timezone.utc)
        db.session.commit()
