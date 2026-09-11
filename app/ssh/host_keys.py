"""SSH host key verification.

SCARLET never uses ``AutoAddPolicy``. Each target host stores an approved host
key. Connections are only allowed when the presented key matches the approved
one. When no key is approved:

* ``strict`` (default, mandatory in production): the presented key is recorded
  as *pending* and the connection is refused until an administrator approves
  the fingerprint;
* ``tofu`` (development only): the first key seen is stored as approved.

A key that differs from the approved one is always a hard failure and raises a
security event.
"""

from __future__ import annotations

import base64
import hashlib
import socket
from collections.abc import Callable
from dataclasses import dataclass

import paramiko

from app.errors import SSHConnectionError, SSHHostKeyError, SSHTimeoutError


@dataclass(frozen=True)
class HostKeyRecord:
    key_type: str  # e.g. ssh-ed25519
    key_base64: str
    fingerprint: str  # SHA256:...

    @classmethod
    def from_pkey(cls, key: paramiko.PKey) -> HostKeyRecord:
        return cls(key.get_name(), key.get_base64(), fingerprint_of(key))

    def to_pkey(self) -> paramiko.PKey:
        return pkey_from_base64(self.key_type, self.key_base64)

    def as_known_hosts_line(self, hostname: str, port: int) -> str:
        entry = hostname if port == 22 else f"[{hostname}]:{port}"
        return f"{entry} {self.key_type} {self.key_base64}"


def fingerprint_of(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def pkey_from_base64(key_type: str, key_base64: str) -> paramiko.PKey:
    data = base64.b64decode(key_base64)
    if key_type == "ssh-rsa":
        return paramiko.RSAKey(data=data)
    if key_type == "ssh-ed25519":
        return paramiko.Ed25519Key(data=data)
    if key_type.startswith("ecdsa-sha2-"):
        return paramiko.ECDSAKey(data=data)
    if key_type == "ssh-dss":  # pragma: no cover - legacy
        return paramiko.DSSKey(data=data)
    raise SSHHostKeyError(f"Unsupported host key type {key_type}.")


class HostKeyMismatch(Exception):
    def __init__(self, presented: HostKeyRecord) -> None:
        self.presented = presented
        super().__init__("host key mismatch")


class ScarletHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Invoked by paramiko only when no key is registered for the host."""

    def __init__(
        self,
        mode: str,
        on_pending: Callable[[HostKeyRecord], None] | None = None,
        on_accept: Callable[[HostKeyRecord], None] | None = None,
    ) -> None:
        self.mode = mode
        self.on_pending = on_pending
        self.on_accept = on_accept

    def missing_host_key(
        self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey
    ) -> None:
        record = HostKeyRecord.from_pkey(key)
        if self.mode == "tofu":
            client.get_host_keys().add(hostname, key.get_name(), key)
            if self.on_accept:
                self.on_accept(record)
            return
        if self.on_pending:
            self.on_pending(record)
        raise SSHHostKeyError(
            "The host key is not approved. Fingerprint recorded for administrator review: "
            f"{record.fingerprint}",
            details={"fingerprint": record.fingerprint, "key_type": record.key_type},
        )


def host_entry(hostname: str, port: int) -> str:
    return hostname if port == 22 else f"[{hostname}]:{port}"


def fetch_host_key(hostname: str, port: int, timeout: int = 10) -> HostKeyRecord:
    """Retrieve the server host key without authenticating (like ssh-keyscan)."""
    sock = None
    transport = None
    try:
        sock = socket.create_connection((hostname, port), timeout=timeout)
        transport = paramiko.Transport(sock)
        transport.banner_timeout = timeout
        transport.start_client(timeout=timeout)
        key = transport.get_remote_server_key()
        return HostKeyRecord.from_pkey(key)
    except TimeoutError as exc:
        raise SSHTimeoutError(f"Timed out fetching host key from {hostname}:{port}.") from exc
    except (OSError, paramiko.SSHException) as exc:
        raise SSHConnectionError(f"Unable to fetch host key from {hostname}:{port}: {exc}") from exc
    finally:
        if transport is not None:
            transport.close()
        if sock is not None:
            sock.close()
