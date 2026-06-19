"""Probe registration, key provisioning, heartbeat service."""

from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone

import structlog
from flask import current_app

from app.crypto.probe_crypto import ProbeProvisioningSession
from app.extensions import db
from app.middleware.audit_middleware import record_audit
from app.models.probe import Probe, ProbeKey, ProbeRegistrationToken
from app.repositories.probe_repo import ProbeRepository, ProbeTokenRepository

log = structlog.get_logger(__name__)


def _generate_token() -> str:
    """PRB-XXXXXXXXXXXX — 12 uppercase alphanumeric chars."""
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"PRB-{suffix}"


class ProbeService:
    def __init__(self) -> None:
        self._probe_repo = ProbeRepository()
        self._token_repo = ProbeTokenRepository()

    # ── Token generation ───────────────────────────────────────────────────

    def generate_registration_token(
        self,
        tenant_id: str,
        created_by: str,
        label: str | None = None,
        expiry_hours: int | None = None,
    ) -> ProbeRegistrationToken:
        if expiry_hours is None:
            expiry_hours = current_app.config.get("PROBE_TOKEN_EXPIRY_HOURS", 24)

        token_str = _generate_token()
        # Ensure uniqueness
        while self._token_repo.get_by_token(token_str):
            token_str = _generate_token()

        token = ProbeRegistrationToken(
            tenant_id=tenant_id,
            token=token_str,
            label=label,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
            created_by=created_by,
        )
        db.session.add(token)
        record_audit(
            "probe_token.generate",
            resource_type="probe_registration_token",
            resource_id=token.id,
            payload={"label": label},
        )
        db.session.commit()
        log.info("probe_token_generated", tenant_id=tenant_id, token_id=token.id)
        return token

    # ── Registration flow ──────────────────────────────────────────────────

    def register_probe(self, registration_data: dict) -> dict:
        """
        Phase 1: Validate token, create Probe record.
        Returns basic probe info — keys not yet provisioned.
        """
        token_str = registration_data["registration_token"]
        token = self._token_repo.get_by_token(token_str)

        if not token or not token.is_valid:
            raise ValueError("Invalid or expired registration token")

        # Check tenant probe limit
        tenant = token.tenant
        existing_count = len(self._probe_repo.list_by_tenant(token.tenant_id))
        if existing_count >= tenant.max_probes:
            raise ValueError(f"Probe limit ({tenant.max_probes}) reached for this tenant")

        # Prevent duplicate machine_id within same tenant
        if self._probe_repo.get_by_machine_id(registration_data["machine_id"], token.tenant_id):
            raise ValueError("A probe with this machine_id is already registered for this tenant")

        probe = Probe(
            tenant_id=token.tenant_id,
            hostname=registration_data["hostname"],
            machine_id=registration_data["machine_id"],
            platform=registration_data.get("platform"),
            architecture=registration_data.get("architecture"),
            docker_version=registration_data.get("docker_version"),
            agent_version=registration_data.get("agent_version"),
            name=registration_data.get("hostname"),
            status="pending_keys",
        )

        # Network inventory reported at registration (interfaces + subnets).
        network = registration_data.get("network")
        if isinstance(network, dict):
            if network.get("interfaces") is not None:
                probe.interfaces = network["interfaces"]
            if network.get("subnets") is not None:
                probe.subnets = network["subnets"]
            probe.network_updated_at = datetime.now(timezone.utc)

        db.session.add(probe)

        # Mark token as used
        token.used = True
        token.used_at = datetime.now(timezone.utc)
        token.used_by_probe_id = probe.id

        record_audit(
            "probe.register",
            resource_type="probe",
            resource_id=probe.id,
            tenant_id=token.tenant_id,
            payload={"hostname": probe.hostname},
        )
        db.session.commit()
        log.info("probe_registered", probe_id=probe.id, tenant_id=probe.tenant_id)

        return {"probe_id": probe.id, "probe_uuid": probe.uuid, "status": "pending_keys"}

    # ── Key provisioning ───────────────────────────────────────────────────

    def provision_keys(self, probe_id: str, probe_sign_pub: str, probe_exchange_pub: str) -> dict:
        """
        Phase 2: Perform X25519 DH handshake, persist only public keys + fingerprint.
        """
        probe = self._probe_repo.get_by_id(probe_id)
        if not probe:
            raise ValueError("Probe not found")
        if probe.key_provisioned:
            raise ValueError("Keys already provisioned — use /rotate-keys")

        session = ProbeProvisioningSession()
        result = session.process_probe_keys(probe_sign_pub, probe_exchange_pub)

        probe.public_sign_key = probe_sign_pub
        probe.public_exchange_key = probe_exchange_pub
        probe.server_sign_public_key = result["server_sign_public_key"]
        probe.server_exchange_public_key = result["server_exchange_public_key"]
        probe.server_side_fingerprint = result["fingerprint"]
        probe.key_provisioned = True
        probe.status = "offline"

        # Store key history
        key_record = ProbeKey(
            probe_id=probe.id,
            tenant_id=probe.tenant_id,
            probe_sign_public_key=probe_sign_pub,
            probe_exchange_public_key=probe_exchange_pub,
            server_sign_public_key=result["server_sign_public_key"],
            server_exchange_public_key=result["server_exchange_public_key"],
            fingerprint=result["fingerprint"],
        )
        db.session.add(key_record)

        record_audit("probe.provision_keys", resource_type="probe", resource_id=probe_id)
        db.session.commit()
        log.info("probe_keys_provisioned", probe_id=probe_id)

        return result["response"]

    # ── Key rotation ───────────────────────────────────────────────────────

    def rotate_keys(self, probe_id: str, probe_sign_pub: str, probe_exchange_pub: str) -> dict:
        probe = self._probe_repo.get_by_id(probe_id)
        if not probe:
            raise ValueError("Probe not found")

        # Revoke old active key record
        from app.models.probe import ProbeKey
        from sqlalchemy import select
        stmt = select(ProbeKey).where(ProbeKey.probe_id == probe_id, ProbeKey.active == True)
        old_keys = db.session.execute(stmt).scalars().all()
        for k in old_keys:
            k.active = False
            k.revoked_at = datetime.now(timezone.utc)

        # Issue new keys
        response = self.provision_keys.__wrapped__(self, probe_id, probe_sign_pub, probe_exchange_pub)  # type: ignore
        probe.keys_rotated_at = datetime.now(timezone.utc)
        probe.key_provisioned = False  # reset so provision_keys proceeds
        result = self.provision_keys(probe_id, probe_sign_pub, probe_exchange_pub)

        record_audit("probe.rotate_keys", resource_type="probe", resource_id=probe_id)
        return result

    # ── Heartbeat ──────────────────────────────────────────────────────────

    def heartbeat(self, probe_id: str, metrics: dict | None = None) -> Probe:
        probe = self._probe_repo.get_by_id(probe_id)
        if not probe:
            raise ValueError("Probe not found")
        if not probe.enabled:
            raise ValueError("Probe is disabled")

        self._probe_repo.update_heartbeat(probe, status="online")

        if metrics:
            from app.services.accounting_service import AccountingService
            AccountingService().record_usage(probe.tenant_id, probe.id, metrics)

        db.session.commit()
        return probe

    def get_probe(self, probe_id: str) -> Probe:
        probe = self._probe_repo.get_by_id(probe_id)
        if not probe:
            raise ValueError("Probe not found")
        return probe

    def update_probe(
        self, probe_id: str, tenant_id: str | None, is_superadmin: bool, **fields
    ) -> Probe:
        """Update operator-editable probe metadata (name, location, contact, notes)."""
        probe = self._probe_repo.get_by_id(probe_id)
        if not probe:
            raise ValueError("Probe not found")
        if not is_superadmin and probe.tenant_id != tenant_id:
            raise PermissionError("Cannot edit a probe from another tenant")

        allowed = {"name", "location", "contact", "notes"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        for k, v in updates.items():
            setattr(probe, k, v)

        record_audit("probe.update", resource_type="probe", resource_id=probe_id,
                     tenant_id=probe.tenant_id, payload=updates)
        db.session.commit()
        log.info("probe_updated", probe_id=probe_id, fields=list(updates))
        return probe

    def list_probes(self, tenant_id: str) -> list[Probe]:
        return self._probe_repo.list_by_tenant(tenant_id)
