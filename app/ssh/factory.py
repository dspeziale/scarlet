"""Build SSH clients for target hosts.

The factory is the single place where credentials are decrypted. It wires the
host key callbacks so that pending/mismatching keys are recorded on the host
record and a security event is raised.
"""

from __future__ import annotations

from collections.abc import Callable

from flask import current_app

from app.config.logging import get_logger
from app.errors import SSHAuthenticationError, SSHHostKeyError
from app.models.enums import CredentialType, HostKeyStatus
from app.models.host import TargetHost
from app.security.crypto import get_cipher
from app.ssh.client import SSHAuth, SSHClient, SSHConnectionParams
from app.ssh.host_keys import HostKeyRecord

log = get_logger(__name__)


class SSHClientFactory:
    """Creates connected ``SSHClient`` instances for ``TargetHost`` records."""

    def __init__(
        self, on_pending_key: Callable | None = None, on_mismatch: Callable | None = None
    ) -> None:
        self._on_pending_key = on_pending_key
        self._on_mismatch = on_mismatch

    def build_params(
        self,
        host: TargetHost,
        *,
        connect_timeout: int | None = None,
        command_timeout: int | None = None,
    ) -> SSHConnectionParams:
        cfg = current_app.config
        credential = host.active_credential
        if credential is None:
            raise SSHAuthenticationError(
                f"Host '{host.name}' has no active SSH credential. Add one before connecting."
            )
        cipher = get_cipher()
        secret = cipher.decrypt(credential.encrypted_secret)
        passphrase = (
            cipher.decrypt(credential.encrypted_passphrase)
            if credential.encrypted_passphrase
            else None
        )
        username = credential.username or host.ssh_username
        if credential.credential_type == CredentialType.PASSWORD.value:
            auth = SSHAuth(username=username, password=secret)
        elif credential.credential_type == CredentialType.PRIVATE_KEY.value:
            auth = SSHAuth(username=username, private_key=secret, passphrase=passphrase)
        else:
            raise SSHAuthenticationError("The active credential is not an SSH credential.")

        host_key = None
        if (
            host.ssh_host_key
            and host.ssh_host_key_type
            and host.ssh_host_key_status == HostKeyStatus.APPROVED.value
        ):
            host_key = HostKeyRecord(
                host.ssh_host_key_type, host.ssh_host_key, host.ssh_fingerprint or ""
            )
        elif host.ssh_host_key_status == HostKeyStatus.REVOKED.value:
            raise SSHHostKeyError(
                "The host key for this host has been revoked. Approve a new key first."
            )

        policy = cfg.get("SCARLET_SSH_HOST_KEY_POLICY", "strict")
        host_id = host.id

        def _pending(record: HostKeyRecord) -> None:
            if self._on_pending_key:
                self._on_pending_key(host_id, record)

        def _accepted(record: HostKeyRecord) -> None:
            if self._on_pending_key:
                self._on_pending_key(host_id, record, accepted=True)

        def _mismatch(record: HostKeyRecord) -> None:
            if self._on_mismatch:
                self._on_mismatch(host_id, record)

        return SSHConnectionParams(
            hostname=host.address,
            port=host.ssh_port,
            auth=auth,
            connect_timeout=connect_timeout or int(cfg.get("SCARLET_SSH_TIMEOUT", 30)),
            command_timeout=command_timeout or int(cfg.get("SCARLET_SSH_COMMAND_TIMEOUT", 600)),
            host_key=host_key,
            host_key_policy=policy,
            on_pending_key=_pending,
            on_accepted_key=_accepted,
            on_mismatch=_mismatch,
            label=host.name,
        )

    def connect(self, host: TargetHost, **kwargs) -> SSHClient:
        params = self.build_params(host, **kwargs)
        return SSHClient(params).connect()


def get_ssh_factory() -> SSHClientFactory:
    """Return the factory registered on the app (tests register a fake)."""
    factory = current_app.extensions.get("scarlet_ssh_factory")
    if factory is None:
        from app.services.host_key_service import on_host_key_mismatch, on_host_key_pending

        factory = SSHClientFactory(
            on_pending_key=on_host_key_pending, on_mismatch=on_host_key_mismatch
        )
        current_app.extensions["scarlet_ssh_factory"] = factory
    return factory
