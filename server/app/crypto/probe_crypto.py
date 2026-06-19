"""
Cryptographic provisioning for probe key exchange.

Protocol:
  1. Probe generates  (X25519_probe_priv, X25519_probe_pub)
                      (Ed25519_probe_priv, Ed25519_probe_pub)
  2. Server generates (X25519_server_priv, X25519_server_pub)
                      (Ed25519_server_priv, Ed25519_server_pub)  [ephemeral, per probe]
  3. Probe sends probe public keys → server
  4. Server derives shared secret via X25519(server_priv, probe_pub)
  5. HKDF-SHA256 derives session_key, transport_key, rotation_key
  6. Server sends back server public keys + fingerprint
  7. Probe derives same keys via X25519(probe_priv, server_pub)

Server NEVER stores its private keys or the shared secret.
Only public keys and the fingerprint are persisted.
"""

from __future__ import annotations

import hashlib
import os
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


# ── Key generation ────────────────────────────────────────────────────────────

def generate_x25519_keypair() -> tuple[X25519PrivateKey, bytes]:
    """Returns (private_key_obj, public_key_bytes)."""
    priv = X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return priv, pub


def generate_ed25519_keypair() -> tuple[Ed25519PrivateKey, bytes]:
    """Returns (private_key_obj, public_key_bytes)."""
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return priv, pub


# ── Key derivation ────────────────────────────────────────────────────────────

def derive_session_keys(
    shared_secret: bytes,
    salt: bytes | None = None,
) -> dict[str, bytes]:
    """
    HKDF-SHA256 → session_key (32 B) | transport_key (32 B) | rotation_key (32 B).
    """
    if salt is None:
        salt = os.urandom(32)

    material = HKDF(
        algorithm=hashes.SHA256(),
        length=96,
        salt=salt,
        info=b"soc-seattle-probe-v1",
    ).derive(shared_secret)

    return {
        "session_key": material[:32],
        "transport_key": material[32:64],
        "rotation_key": material[64:],
        "salt": salt,
    }


def compute_fingerprint(
    probe_sign_pub: bytes,
    probe_exchange_pub: bytes,
    server_sign_pub: bytes,
    server_exchange_pub: bytes,
) -> str:
    """SHA-256 fingerprint over concatenated public keys."""
    h = hashlib.sha256(
        probe_sign_pub + probe_exchange_pub + server_sign_pub + server_exchange_pub
    )
    return h.hexdigest()


# ── Server-side provisioning ──────────────────────────────────────────────────

class ProbeProvisioningSession:
    """
    Ephemeral server-side session for a single probe provisioning handshake.

    Usage:
        session = ProbeProvisioningSession()
        result = session.process_probe_keys(probe_sign_pub_hex, probe_exchange_pub_hex)
        # persist result["server_sign_public_key"], result["server_exchange_public_key"],
        #          result["fingerprint"]
        # send result to probe
    """

    def __init__(self) -> None:
        self._server_exchange_priv, self._server_exchange_pub = generate_x25519_keypair()
        self._server_sign_priv, self._server_sign_pub = generate_ed25519_keypair()

    def process_probe_keys(
        self, probe_sign_pub_hex: str, probe_exchange_pub_hex: str
    ) -> dict:
        probe_sign_pub = bytes.fromhex(probe_sign_pub_hex)
        probe_exchange_pub = bytes.fromhex(probe_exchange_pub_hex)

        # X25519 DH
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
        peer_pub = X25519PublicKey.from_public_bytes(probe_exchange_pub)
        shared_secret = self._server_exchange_priv.exchange(peer_pub)

        salt = os.urandom(32)
        derived = derive_session_keys(shared_secret, salt=salt)

        server_sign_pub_hex = self._server_sign_pub.hex()
        server_exchange_pub_hex = self._server_exchange_pub.hex()

        fingerprint = compute_fingerprint(
            probe_sign_pub, probe_exchange_pub,
            self._server_sign_pub, self._server_exchange_pub,
        )

        # Sign the fingerprint so the probe can verify server identity
        sig = self._server_sign_priv.sign(bytes.fromhex(fingerprint))

        return {
            # To persist in DB
            "server_sign_public_key": server_sign_pub_hex,
            "server_exchange_public_key": server_exchange_pub_hex,
            "fingerprint": fingerprint,
            # To send back to probe (do NOT store derived keys)
            "response": {
                "server_sign_public_key": server_sign_pub_hex,
                "server_exchange_public_key": server_exchange_pub_hex,
                "salt": salt.hex(),
                "fingerprint": fingerprint,
                "server_fingerprint_signature": sig.hex(),
            },
        }


# ── AES-256-GCM helpers ───────────────────────────────────────────────────────

def aes_gcm_encrypt(key: bytes, plaintext: bytes, aad: bytes | None = None) -> dict:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext, aad)
    return {"nonce": nonce.hex(), "ciphertext": ct.hex()}


def aes_gcm_decrypt(key: bytes, nonce_hex: str, ciphertext_hex: str, aad: bytes | None = None) -> bytes:
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(bytes.fromhex(nonce_hex), bytes.fromhex(ciphertext_hex), aad)
