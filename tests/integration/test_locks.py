import pytest

from app.errors import ConcurrencyError
from app.lifecycle.locks import DatabaseLockBackend, LockManager, runtime_lock_key

pytestmark = pytest.mark.integration


def test_database_lock_exclusive(app):
    manager = LockManager(DatabaseLockBackend(), default_ttl=60)
    key = runtime_lock_key(1, 1)
    with manager.hold(key, description="op A"):
        assert manager.is_locked(key)
        with pytest.raises(ConcurrencyError) as exc, manager.hold(key, description="op B"):
            pass
        assert "Another operation" in exc.value.message
    assert not manager.is_locked(key)


def test_lock_released_on_error(app):
    manager = LockManager(DatabaseLockBackend(), default_ttl=60)
    key = runtime_lock_key(2, 2)
    with pytest.raises(RuntimeError), manager.hold(key):
        raise RuntimeError("boom")
    assert not manager.is_locked(key)


def test_expired_lock_is_recoverable(app):
    from datetime import timedelta

    from app.extensions import db
    from app.models.lifecycle import DistributedLock
    from app.utils.time import utcnow

    backend = DatabaseLockBackend()
    key = runtime_lock_key(3, 3)
    db.session.add(
        DistributedLock(
            key=key,
            owner="crashed-worker",
            acquired_at=utcnow() - timedelta(hours=2),
            expires_at=utcnow() - timedelta(hours=1),
        )
    )
    db.session.commit()
    assert backend.info(key) is None  # expired => not considered held
    assert backend.acquire(key, "new-owner", 60)
    assert backend.info(key)["owner"] == "new-owner"
    assert not backend.release(key, "someone-else")
    assert backend.release(key, "new-owner")


def test_extend(app):
    backend = DatabaseLockBackend()
    key = runtime_lock_key(4, 4)
    assert backend.acquire(key, "o", 30)
    assert backend.extend(key, "o", 120)
    assert not backend.extend(key, "x", 120)
    backend.release(key, "o")
