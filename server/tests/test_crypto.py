"""Unit tests for the cryptographic provisioning module."""

import pytest


class TestKeyGeneration:
    def test_x25519_keypair(self, app):
        with app.app_context():
            from app.crypto.probe_crypto import generate_x25519_keypair
            priv, pub = generate_x25519_keypair()
            assert priv is not None
            assert len(pub) == 32

    def test_ed25519_keypair(self, app):
        with app.app_context():
            from app.crypto.probe_crypto import generate_ed25519_keypair
            priv, pub = generate_ed25519_keypair()
            assert priv is not None
            assert len(pub) == 32


class TestKeyDerivation:
    def test_hkdf_produces_three_keys(self, app):
        with app.app_context():
            import os
            from app.crypto.probe_crypto import derive_session_keys
            shared_secret = os.urandom(32)
            result = derive_session_keys(shared_secret)
            assert "session_key" in result
            assert "transport_key" in result
            assert "rotation_key" in result
            assert len(result["session_key"]) == 32
            assert len(result["transport_key"]) == 32
            assert len(result["rotation_key"]) == 32

    def test_same_secret_same_keys(self, app):
        with app.app_context():
            import os
            from app.crypto.probe_crypto import derive_session_keys
            secret = os.urandom(32)
            salt = os.urandom(32)
            k1 = derive_session_keys(secret, salt=salt)
            k2 = derive_session_keys(secret, salt=salt)
            assert k1["session_key"] == k2["session_key"]

    def test_fingerprint_is_hex(self, app):
        with app.app_context():
            import os
            from app.crypto.probe_crypto import compute_fingerprint
            fp = compute_fingerprint(os.urandom(32), os.urandom(32), os.urandom(32), os.urandom(32))
            assert len(fp) == 64  # SHA-256 hex
            int(fp, 16)  # valid hex


class TestProvisioningSession:
    def test_full_handshake(self, app):
        with app.app_context():
            from app.crypto.probe_crypto import (
                ProbeProvisioningSession,
                generate_x25519_keypair,
                generate_ed25519_keypair,
            )
            # Probe generates keys
            _, probe_sign_pub = generate_ed25519_keypair()
            _, probe_exchange_pub = generate_x25519_keypair()

            # Server processes them
            session = ProbeProvisioningSession()
            result = session.process_probe_keys(
                probe_sign_pub.hex(), probe_exchange_pub.hex()
            )

            assert "server_sign_public_key" in result
            assert "fingerprint" in result
            assert "response" in result
            assert len(result["fingerprint"]) == 64


class TestAESGCM:
    def test_encrypt_decrypt(self, app):
        with app.app_context():
            import os
            from app.crypto.probe_crypto import aes_gcm_encrypt, aes_gcm_decrypt
            key = os.urandom(32)
            plaintext = b"hello world"
            enc = aes_gcm_encrypt(key, plaintext)
            dec = aes_gcm_decrypt(key, enc["nonce"], enc["ciphertext"])
            assert dec == plaintext

    def test_wrong_key_fails(self, app):
        with app.app_context():
            import os
            from app.crypto.probe_crypto import aes_gcm_encrypt, aes_gcm_decrypt
            from cryptography.exceptions import InvalidTag
            key = os.urandom(32)
            wrong_key = os.urandom(32)
            enc = aes_gcm_encrypt(key, b"secret")
            with pytest.raises(Exception):
                aes_gcm_decrypt(wrong_key, enc["nonce"], enc["ciphertext"])
