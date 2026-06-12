import base64
import secrets
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def generate_x25519_keypair():
    private_key = x25519.X25519PrivateKey.generate()
    public_key = private_key.public_key()
    
    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )
    
    return encode_base64(priv_bytes), encode_base64(pub_bytes)

def compute_shared_secret(private_key_b64: str, peer_public_key_b64: str) -> str:
    priv_bytes = decode_base64(private_key_b64)
    peer_pub_bytes = decode_base64(peer_public_key_b64)
    
    private_key = x25519.X25519PrivateKey.from_private_bytes(priv_bytes)
    peer_public_key = x25519.X25519PublicKey.from_public_bytes(peer_pub_bytes)
    
    shared_secret = private_key.exchange(peer_public_key)
    return encode_base64(shared_secret)

def derive_session_key(shared_secret_b64: str, salt_b64: str = None) -> str:
    shared_secret = decode_base64(shared_secret_b64)
    salt = decode_base64(salt_b64) if salt_b64 else None
    
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=b'scarlet-session-key',
    )
    
    session_key = hkdf.derive(shared_secret)
    return encode_base64(session_key)

def encrypt_aes_gcm(key_b64: str, plaintext: str) -> tuple[str, str]:
    """Encrypts plaintext with AES-GCM and returns (nonce_b64, ciphertext_b64)"""
    key = decode_base64(key_b64)
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12) # 96-bit nonce is standard for GCM
    
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    
    return encode_base64(nonce), encode_base64(ciphertext)

def encode_base64(data: bytes) -> str:
    return base64.b64encode(data).decode('utf-8')

def decode_base64(data_str: str) -> bytes:
    return base64.b64decode(data_str.encode('utf-8'))
