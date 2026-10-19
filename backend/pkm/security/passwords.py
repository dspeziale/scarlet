"""Password hashing (Argon2id) and password policy."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)

# A short deny-list of the most common passwords; length is the main control.
_COMMON = {
    "password", "password1", "password123", "123456789012", "qwertyuiopas", "administrator",
    "changeme1234", "welcome12345", "passw0rd1234", "admin1234567", "kubernetes123",
}  # fmt: skip

# Pre-computed hash used to keep timing uniform when the user does not exist.
_DUMMY_HASH = _hasher.hash("pkm-dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, *, username: str, min_length: int) -> list[str]:
    """Return a list of policy violation codes (empty = acceptable)."""
    problems: list[str] = []
    if len(password) < min_length:
        problems.append("too_short")
    if len(password) > 256:
        problems.append("too_long")
    if password.lower() in _COMMON:
        problems.append("too_common")
    if username and username.lower() in password.lower():
        problems.append("contains_username")
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        problems.append("not_enough_character_classes")
    return problems
