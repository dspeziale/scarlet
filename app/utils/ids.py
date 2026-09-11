"""Identifier helpers (ULID-like request IDs, human readable references)."""

from __future__ import annotations

import os
import secrets
import time
from datetime import datetime

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32


def _encode(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_request_id() -> str:
    """Return a 26 character, time-sortable ULID string."""
    ts = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    return _encode(ts, 10) + _encode(rand, 16)


def new_reference(prefix: str, sequence: int, when: datetime | None = None) -> str:
    """Return a human readable reference such as ``DEP-20260911-000123``."""
    from app.utils.time import utcnow

    when = when or utcnow()
    return f"{prefix}-{when:%Y%m%d}-{sequence:06d}"


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)
