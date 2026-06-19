"""Probe repository."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.extensions import db
from app.models.probe import Probe, ProbeRegistrationToken
from app.repositories.base import BaseRepository


class ProbeRepository(BaseRepository[Probe]):
    model = Probe

    def get_by_uuid(self, probe_uuid: str) -> Probe | None:
        stmt = self._tenant_filter(select(Probe).where(Probe.uuid == probe_uuid))
        return db.session.execute(stmt).scalar_one_or_none()

    def get_by_machine_id(self, machine_id: str, tenant_id: str) -> Probe | None:
        stmt = select(Probe).where(Probe.machine_id == machine_id, Probe.tenant_id == tenant_id)
        return db.session.execute(stmt).scalar_one_or_none()

    def list_by_tenant(self, tenant_id: str, limit: int = 100, offset: int = 0) -> list[Probe]:
        stmt = (
            select(Probe)
            .where(Probe.tenant_id == tenant_id)
            .order_by(Probe.registered_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(db.session.execute(stmt).scalars())

    def update_heartbeat(self, probe: Probe, status: str = "online") -> Probe:
        probe.last_seen = datetime.now(timezone.utc)
        probe.status = status
        db.session.flush()
        return probe


class ProbeTokenRepository(BaseRepository[ProbeRegistrationToken]):
    model = ProbeRegistrationToken

    def get_by_token(self, token: str) -> ProbeRegistrationToken | None:
        stmt = select(ProbeRegistrationToken).where(ProbeRegistrationToken.token == token)
        return db.session.execute(stmt).scalar_one_or_none()

    def list_by_tenant(self, tenant_id: str) -> list[ProbeRegistrationToken]:
        stmt = (
            select(ProbeRegistrationToken)
            .where(ProbeRegistrationToken.tenant_id == tenant_id)
            .order_by(ProbeRegistrationToken.created_at.desc())
        )
        return list(db.session.execute(stmt).scalars())
