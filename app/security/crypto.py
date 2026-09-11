"""Encryption at rest for credentials and secrets.

The application encryption key comes from ``SCARLET_CREDENTIAL_ENCRYPTION_KEY``.
It may be either a raw Fernet key (44 url-safe base64 characters, produced by
``flask scarlet gen-key``) or an arbitrary high-entropy string, in which case a
Fernet key is derived from it with HKDF-SHA256.

Key rotation: set ``SCARLET_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS`` to the old key,
deploy, run ``flask scarlet rotate-credentials`` and finally drop the previous key.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.errors import ConfigurationError, SecurityError

_HKDF_INFO = b"scarlet-credential-encryption-v1"
_HKDF_SALT = b"scarlet-static-salt-v1"  # deterministic derivation is intentional


def derive_fernet_key(material: str) -> bytes:
    """Return a Fernet key for ``material`` (raw Fernet key or arbitrary secret)."""
    if not material:
        raise ConfigurationError("Encryption key material is empty")
    raw = material.strip().encode()
    if len(raw) == 44:
        try:
            decoded = base64.urlsafe_b64decode(raw)
            if len(decoded) == 32:
                return raw
        except Exception:  # noqa: BLE001 - fall through to derivation
            pass
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT, info=_HKDF_INFO)
    return base64.urlsafe_b64encode(hkdf.derive(raw))


class CredentialCipher:
    """Symmetric authenticated encryption (Fernet: AES-128-CBC + HMAC-SHA256)."""

    def __init__(self, key: str, previous_key: str | None = None) -> None:
        primary = Fernet(derive_fernet_key(key))
        fernets = [primary]
        if previous_key:
            fernets.append(Fernet(derive_fernet_key(previous_key)))
        self._fernet = MultiFernet(fernets)
        self._primary = primary
        self.key_id = hashlib.sha256(derive_fernet_key(key)).hexdigest()[:12]

    def encrypt(self, plaintext: str | bytes) -> str:
        data = plaintext.encode() if isinstance(plaintext, str) else plaintext
        return self._primary.encrypt(data).decode()

    def decrypt(self, token: str | bytes) -> str:
        data = token.encode() if isinstance(token, str) else token
        try:
            return self._fernet.decrypt(data).decode()
        except InvalidToken as exc:
            raise SecurityError(
                "Stored credential cannot be decrypted with the configured encryption key."
            ) from exc

    def decrypt_bytes(self, token: str | bytes) -> bytes:
        data = token.encode() if isinstance(token, str) else token
        try:
            return self._fernet.decrypt(data)
        except InvalidToken as exc:
            raise SecurityError(
                "Stored credential cannot be decrypted with the configured encryption key."
            ) from exc

    def rotate(self, token: str) -> str:
        """Re-encrypt ``token`` with the primary key (no-op if already current)."""
        return self._fernet.rotate(token.encode()).decode()

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def get_cipher() -> CredentialCipher:
    """Return the cipher bound to the current Flask application."""
    from flask import current_app

    cipher = current_app.extensions.get("scarlet_cipher")
    if cipher is None:
        cipher = CredentialCipher(
            current_app.config["SCARLET_CREDENTIAL_ENCRYPTION_KEY"],
            current_app.config.get("SCARLET_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS") or None,
        )
        current_app.extensions["scarlet_cipher"] = cipher
    return cipher
