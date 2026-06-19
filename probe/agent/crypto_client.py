"""
Cryptographic identity management for the probe agent.

Generates and persists Ed25519 signing key + X25519 exchange key.
Performs the DH handshake with the server during registration/provisioning.
Private keys are stored locally in KEY_FILE; secrets derived during DH
are NEVER persisted.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import TypedDict

import structlog
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from nacl.signing import SigningKey

log = structlog.get_logger(__name__)


class StoredKeys(TypedDict):
    sign_private_hex: str
    sign_public_hex: str
    exchange_private_hex: str
    exchange_public_hex: str


class ProbeKeys:
    """Loaded or freshly-generated keypair for this probe."""

    def __init__(self, key_file: Path) -> None:
        self._key_file = key_file
        if key_file.exists():
            self._load()
        else:
            self._generate()

    def _generate(self) -> None:
        # Ed25519 signing key
        signing_key = SigningKey.generate()
        self._sign_priv: bytes = bytes(signing_key)
        self._sign_pub: bytes = bytes(signing_key.verify_key)

        # X25519 exchange key
        exchange_priv = X25519PrivateKey.generate()
        self._exchange_priv: bytes = exchange_priv.private_bytes_raw()
        self._exchange_pub: bytes = exchange_priv.public_key().public_bytes_raw()

        self._persist()
        log.info("probe_keys_generated")

    def _load(self) -> None:
        data: StoredKeys = json.loads(self._key_file.read_text())
        self._sign_priv = bytes.fromhex(data["sign_private_hex"])
        self._sign_pub = bytes.fromhex(data["sign_public_hex"])
        self._exchange_priv = bytes.fromhex(data["exchange_private_hex"])
        self._exchange_pub = bytes.fromhex(data["exchange_public_hex"])
        log.info("probe_keys_loaded")

    def _persist(self) -> None:
        self._key_file.parent.mkdir(parents=True, exist_ok=True)
        payload: StoredKeys = {
            "sign_private_hex": self._sign_priv.hex(),
            "sign_public_hex": self._sign_pub.hex(),
            "exchange_private_hex": self._exchange_priv.hex(),
            "exchange_public_hex": self._exchange_pub.hex(),
        }
        self._key_file.write_text(json.dumps(payload, indent=2))
        self._key_file.chmod(0o600)

    @property
    def sign_public_hex(self) -> str:
        return self._sign_pub.hex()

    @property
    def exchange_public_hex(self) -> str:
        return self._exchange_pub.hex()

    def sign(self, message: bytes) -> bytes:
        from nacl.signing import SigningKey as _SK
        sk = _SK(self._sign_priv)
        return bytes(sk.sign(message).signature)

    def perform_dh(self, server_exchange_pub_hex: str) -> bytes:
        """X25519 DH with server's ephemeral public key. Returns shared secret."""
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey as _X
        server_pub_bytes = bytes.fromhex(server_exchange_pub_hex)
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
        server_pub = X25519PublicKey.from_public_bytes(server_pub_bytes)
        priv = _X.from_private_bytes(self._exchange_priv)
        shared = priv.exchange(server_pub)
        return shared
