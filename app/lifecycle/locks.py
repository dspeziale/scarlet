"""Distributed locks for runtime operations.

Lock key: ``runtime:{target_id}:{application_id}``. Redis ``SET NX PX`` with an
owner token and a Lua compare-and-delete release. When Redis is unavailable
(tests, degraded mode) a database row lock with expiry is used instead. Locks
always expire, so a crashed worker can never leave a permanent stale lock.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from app.config.logging import get_logger
from app.errors import ConcurrencyError
from app.utils.time import utcnow

log = get_logger(__name__)

_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_EXTEND_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("pexpire", KEYS[1], ARGV[2])
else
    return 0
end
"""


def runtime_lock_key(target_id: int, application_id: int) -> str:
    return f"runtime:{int(target_id)}:{int(application_id)}"


def host_lock_key(target_id: int) -> str:
    return f"host:{int(target_id)}"


class LockBackend:
    def acquire(
        self, key: str, owner: str, ttl_seconds: int
    ) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def release(self, key: str, owner: str) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def extend(self, key: str, owner: str, ttl_seconds: int) -> bool:  # pragma: no cover
        raise NotImplementedError

    def info(self, key: str) -> dict[str, Any] | None:  # pragma: no cover
        raise NotImplementedError


class RedisLockBackend(LockBackend):
    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    def acquire(self, key: str, owner: str, ttl_seconds: int) -> bool:
        return bool(self.redis.set(f"scarlet:lock:{key}", owner, nx=True, px=ttl_seconds * 1000))

    def release(self, key: str, owner: str) -> bool:
        return bool(self.redis.eval(_RELEASE_SCRIPT, 1, f"scarlet:lock:{key}", owner))

    def extend(self, key: str, owner: str, ttl_seconds: int) -> bool:
        return bool(
            self.redis.eval(_EXTEND_SCRIPT, 1, f"scarlet:lock:{key}", owner, ttl_seconds * 1000)
        )

    def info(self, key: str) -> dict[str, Any] | None:
        owner = self.redis.get(f"scarlet:lock:{key}")
        if owner is None:
            return None
        ttl = self.redis.pttl(f"scarlet:lock:{key}")
        return {"owner": owner.decode() if isinstance(owner, bytes) else owner, "ttl_ms": ttl}


class DatabaseLockBackend(LockBackend):
    """Row-based lock with expiry. Relies on the unique constraint on ``key``."""

    def acquire(self, key: str, owner: str, ttl_seconds: int) -> bool:
        from sqlalchemy.exc import IntegrityError

        from app.extensions import db
        from app.models.lifecycle import DistributedLock

        now = utcnow()
        existing = db.session.execute(
            db.select(DistributedLock).where(DistributedLock.key == key)
        ).scalar_one_or_none()
        if existing is not None:
            if existing.expires_at > now and not existing.released:
                return False
            existing.owner = owner
            existing.acquired_at = now
            existing.expires_at = now + timedelta(seconds=ttl_seconds)
            existing.released = False
            db.session.commit()
            return True
        try:
            db.session.add(
                DistributedLock(
                    key=key,
                    owner=owner,
                    acquired_at=now,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
            )
            db.session.commit()
            return True
        except IntegrityError:
            db.session.rollback()
            return False

    def release(self, key: str, owner: str) -> bool:
        from app.extensions import db
        from app.models.lifecycle import DistributedLock

        existing = db.session.execute(
            db.select(DistributedLock).where(DistributedLock.key == key)
        ).scalar_one_or_none()
        if existing is None or existing.owner != owner:
            return False
        db.session.delete(existing)
        db.session.commit()
        return True

    def extend(self, key: str, owner: str, ttl_seconds: int) -> bool:
        from app.extensions import db
        from app.models.lifecycle import DistributedLock

        existing = db.session.execute(
            db.select(DistributedLock).where(DistributedLock.key == key)
        ).scalar_one_or_none()
        if existing is None or existing.owner != owner:
            return False
        existing.expires_at = utcnow() + timedelta(seconds=ttl_seconds)
        db.session.commit()
        return True

    def info(self, key: str) -> dict[str, Any] | None:
        from app.extensions import db
        from app.models.lifecycle import DistributedLock

        existing = db.session.execute(
            db.select(DistributedLock).where(DistributedLock.key == key)
        ).scalar_one_or_none()
        if existing is None or existing.expires_at <= utcnow() or existing.released:
            return None
        return {
            "owner": existing.owner,
            "acquired_at": existing.acquired_at.isoformat(),
            "expires_at": existing.expires_at.isoformat(),
        }


class LockManager:
    def __init__(self, backend: LockBackend, default_ttl: int = 1800) -> None:
        self.backend = backend
        self.default_ttl = default_ttl

    @contextmanager
    def hold(
        self, key: str, *, owner: str | None = None, ttl: int | None = None, description: str = ""
    ):
        owner = owner or f"{uuid.uuid4()}"
        ttl = ttl or self.default_ttl
        if not self.backend.acquire(key, owner, ttl):
            info = self.backend.info(key) or {}
            raise ConcurrencyError(
                f"Another operation is already running ({description or key}). Please wait for it to finish.",
                details={"lock_key": key, "holder": info},
            )
        log.debug(
            "lock acquired", extra={"extra_data": {"lock_key": key, "owner": owner, "ttl": ttl}}
        )
        try:
            yield owner
        finally:
            released = self.backend.release(key, owner)
            log.debug(
                "lock released",
                extra={"extra_data": {"lock_key": key, "owner": owner, "released": released}},
            )

    def is_locked(self, key: str) -> bool:
        return self.backend.info(key) is not None

    def info(self, key: str) -> dict[str, Any] | None:
        return self.backend.info(key)


def get_lock_manager() -> LockManager:
    from flask import current_app

    manager = current_app.extensions.get("scarlet_lock_manager")
    if manager is not None:
        return manager
    ttl = int(current_app.config.get("SCARLET_LOCK_TIMEOUT", 1800))
    backend: LockBackend
    if (
        current_app.config.get("TESTING")
        or current_app.config.get("SCARLET_LOCK_BACKEND") == "database"
    ):
        backend = DatabaseLockBackend()
    else:
        try:
            import redis

            client = redis.Redis.from_url(
                current_app.config["REDIS_URL"], socket_connect_timeout=2, socket_timeout=2
            )
            client.ping()
            backend = RedisLockBackend(client)
        except Exception as exc:  # noqa: BLE001
            log.warning("Redis unavailable for locking, falling back to database locks: %s", exc)
            backend = DatabaseLockBackend()
    manager = LockManager(backend, default_ttl=ttl)
    current_app.extensions["scarlet_lock_manager"] = manager
    return manager
