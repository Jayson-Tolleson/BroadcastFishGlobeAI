from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    created_at: float


class TinyTTLCache:
    def __init__(self, ttl_seconds: float = 20.0, max_entries: int = 128) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._store: dict[str, CacheEntry] = {}
        self._last_good: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if not entry:
            return None
        if entry.expires_at < time.time():
            self._store.pop(key, None)
            return None
        return entry.value

    def get_entry(self, key: str) -> CacheEntry | None:
        entry = self._store.get(key)
        if not entry:
            return None
        if entry.expires_at < time.time():
            self._store.pop(key, None)
            return None
        return entry

    def get_last_good(self, key: str) -> Any | None:
        entry = self._last_good.get(key)
        return entry.value if entry else None

    def set(self, key: str, value: Any) -> None:
        now = time.time()
        if len(self._store) >= self.max_entries:
            oldest = min(self._store, key=lambda k: self._store[k].expires_at)
            self._store.pop(oldest, None)
        entry = CacheEntry(value=value, expires_at=now + self.ttl_seconds, created_at=now)
        self._store[key] = entry
        self._last_good[key] = entry

    def stats(self) -> dict[str, int]:
        return {
            "entries": len(self._store),
            "last_good_entries": len(self._last_good),
            "max_entries": self.max_entries,
        }
