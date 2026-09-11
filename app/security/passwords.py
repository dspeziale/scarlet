"""Password hashing (Argon2id) and password policy."""

from __future__ import annotations

import re

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.errors import ValidationError

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

COMMON_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "123456789012",
    "qwertyuiop12",
    "administrator",
    "changeme1234",
    "welcome12345",
    "letmein12345",
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def validate_password_policy(
    password: str, *, min_length: int = 12, require_complexity: bool = True, username: str = ""
) -> None:
    errors: list[str] = []
    if len(password) < min_length:
        errors.append(f"Password must be at least {min_length} characters long.")
    if len(password) > 256:
        errors.append("Password is too long (max 256 characters).")
    if require_complexity:
        classes = sum(
            bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]")
        )
        if classes < 3:
            errors.append(
                "Password must contain at least three of: lowercase, uppercase, digits, symbols."
            )
    if password.lower() in COMMON_PASSWORDS:
        errors.append("Password is too common.")
    if username and username.lower() in password.lower():
        errors.append("Password must not contain the username.")
    if errors:
        raise ValidationError("Password does not meet the policy.", errors={"password": errors})
