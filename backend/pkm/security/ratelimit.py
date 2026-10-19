"""In-memory sliding-window rate limiter (single process deployment)."""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, max_keys: int = 50_000) -> None:
        self.limit = limit
        self.window = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Register a hit. Returns False when the key is over the limit."""
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                if len(self._hits) >= self.max_keys:
                    self._evict(now)
                q = self._hits[key] = deque()
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def retry_after(self, key: str) -> int:
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 0
            return max(1, int(self.window - (time.monotonic() - q[0])) + 1)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def _evict(self, now: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or now - q[-1] > self.window]:
            del self._hits[k]
        if len(self._hits) >= self.max_keys:
            self._hits.clear()
