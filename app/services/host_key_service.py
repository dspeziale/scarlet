"""SSH host key lifecycle: scan, pending approval, approve, revoke, mismatch handling."""

from __future__ import annotations

from flask import current_app

from app.audit import audit
from app.errors import NotFoundError, ValidationError
from app.extensions import db
from app.models.enums import HostKeyStatus, HostStatus, SecurityEventSeverity
from app.models.host import TargetHost
from app.ssh.host_keys import HostKeyRecord, fetch_host_key
from app.utils.time import utcnow


def on_host_key_pending(host_id: int, record: HostKeyRecord, accepted: bool = False) -> None:
    """Callback from the SSH layer: an unknown key was presented."""
    host = db.session.get(TargetHost, host_id)
    if host is None:
        return
    if accepted:  # tofu mode (development only)
        host.ssh_host_key_type = record.key_type
        host.ssh_host_key = record.key_base64
        host.ssh_fingerprint = record.fingerprint
        host.ssh_host_key_status = HostKeyStatus.APPROVED.value
        host.ssh_host_key_approved_at = utcnow()
        db.session.commit()
        audit.record("HOST_KEY_AUTO_ACCEPTED", target=host, entity_type="TargetHost", entity_id=host.id, details={"fingerprint": record.fingerprint, "mode": "tofu"})
        return
    host.ssh_pending_fingerprint = record.fingerprint
    host.ssh_pending_host_key = record.key_base64
    host.ssh_pending_host_key_type = record.key_type
    if host.ssh_host_key_status != HostKeyStatus.MISMATCH.value:
        host.ssh_host_key_status = HostKeyStatus.PENDING_APPROVAL.value
    db.session.commit()
    audit.record("HOST_KEY_PENDING", target=host, entity_type="TargetHost", entity_id=host.id, result="INFO", details={"fingerprint": record.fingerprint, "key_type": record.key_type})


def on_host_key_mismatch(host_id: int, record: HostKeyRecord) -> None:
    """Callback from the SSH layer: the presented key differs from the approved one."""
    host = db.session.get(TargetHost, host_id)
    if host is None:
        return
    host.ssh_host_key_status = HostKeyStatus.MISMATCH.value
    host.ssh_pending_fingerprint = record.fingerprint
    host.ssh_pending_host_key = record.key_base64
    host.ssh_pending_host_key_type = record.key_type
    host.status = HostStatus.OFFLINE.value
    host.last_error = f"SSH host key mismatch (presented {record.fingerprint})"
    db.session.commit()
    audit.security_event(
        "SSH_HOST_KEY_MISMATCH",
        f"Host {host.name} presented an unexpected SSH host key {record.fingerprint} (approved: {host.ssh_fingerprint}).",
        severity=SecurityEventSeverity.CRITICAL,
        target=host,
        details={"presented_fingerprint": record.fingerprint, "approved_fingerprint": host.ssh_fingerprint},
    )
    audit.record("HOST_KEY_MISMATCH", target=host, entity_type="TargetHost", entity_id=host.id, result="FAILURE", details={"presented_fingerprint": record.fingerprint})


class HostKeyService:
    def scan(self, host: TargetHost, *, user=None) -> dict:
        """Fetch the host key without authenticating and store it as pending."""
        record = fetch_host_key(host.address, host.ssh_port, timeout=int(current_app.config.get("SCARLET_SSH_TIMEOUT", 30)))
        if host.ssh_host_key_status == HostKeyStatus.APPROVED.value and host.ssh_host_key == record.key_base64:
            return {"fingerprint": record.fingerprint, "key_type": record.key_type, "status": "MATCHES_APPROVED"}
        host.ssh_pending_fingerprint = record.fingerprint
        host.ssh_pending_host_key = record.key_base64
        host.ssh_pending_host_key_type = record.key_type
        if host.ssh_host_key_status == HostKeyStatus.APPROVED.value:
            host.ssh_host_key_status = HostKeyStatus.MISMATCH.value
            audit.security_event("SSH_HOST_KEY_MISMATCH", f"Scan of {host.name} returned a key different from the approved one.", severity=SecurityEventSeverity.HIGH, target=host, user=user, details={"presented_fingerprint": record.fingerprint, "approved_fingerprint": host.ssh_fingerprint})
        else:
            host.ssh_host_key_status = HostKeyStatus.PENDING_APPROVAL.value
        db.session.commit()
        audit.record("HOST_KEY_SCANNED", user=user, target=host, entity_type="TargetHost", entity_id=host.id, details={"fingerprint": record.fingerprint, "key_type": record.key_type})
        return {"fingerprint": record.fingerprint, "key_type": record.key_type, "status": host.ssh_host_key_status}

    def approve(self, host: TargetHost, fingerprint: str, *, user=None) -> TargetHost:
        """Approve the pending key. The caller must supply the fingerprint they verified."""
        if not host.ssh_pending_host_key or not host.ssh_pending_fingerprint:
            raise NotFoundError("There is no pending host key to approve. Run a scan or test connection first.")
        if (fingerprint or "").strip() != host.ssh_pending_fingerprint:
            raise ValidationError(
                "The fingerprint you confirmed does not match the pending host key.",
                errors={"fingerprint": ["Fingerprint mismatch."]},
            )
        previous = host.ssh_fingerprint
        host.ssh_host_key_type = host.ssh_pending_host_key_type
        host.ssh_host_key = host.ssh_pending_host_key
        host.ssh_fingerprint = host.ssh_pending_fingerprint
        host.ssh_host_key_status = HostKeyStatus.APPROVED.value
        host.ssh_host_key_approved_by_id = getattr(user, "id", None)
        host.ssh_host_key_approved_at = utcnow()
        host.ssh_pending_fingerprint = None
        host.ssh_pending_host_key = None
        host.ssh_pending_host_key_type = None
        host.last_error = None
        db.session.commit()
        audit.record("HOST_KEY_APPROVED", user=user, target=host, entity_type="TargetHost", entity_id=host.id, details={"fingerprint": host.ssh_fingerprint, "previous_fingerprint": previous})
        return host

    def revoke(self, host: TargetHost, *, user=None, reason: str = "") -> TargetHost:
        previous = host.ssh_fingerprint
        host.ssh_host_key = None
        host.ssh_host_key_type = None
        host.ssh_fingerprint = None
        host.ssh_host_key_status = HostKeyStatus.REVOKED.value
        db.session.commit()
        audit.record("HOST_KEY_REVOKED", user=user, target=host, entity_type="TargetHost", entity_id=host.id, details={"previous_fingerprint": previous, "reason": reason})
        return host
