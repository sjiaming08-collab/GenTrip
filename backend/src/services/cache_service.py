"""TTL memory cache for Constraint / POI / Tool Result reuse."""

from __future__ import annotations

import time
from typing import Any


class TTLCache:
    """Simple TTL cache with key-prefix invalidation."""

    def __init__(self, ttl_seconds: int = 300):
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires, value = entry
        if time.monotonic() > expires:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, key_prefix: str) -> int:
        """Invalidate all keys starting with prefix. Returns count removed."""
        to_remove = [k for k in self._store if k.startswith(key_prefix)]
        for k in to_remove:
            del self._store[k]
        return len(to_remove)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
