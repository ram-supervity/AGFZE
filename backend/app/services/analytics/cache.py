"""A small in-process TTL cache for computed aggregates.

Deliberately the simplest thing that works. This platform serves a bounded internal user base
behind a single application process per deployment; a cache server would be another service to
run, monitor and secure in exchange for a saving nobody would be able to measure.

Two properties matter and both are enforced here rather than left to the caller.

The key always carries the scope. Two accounts share a cached entry only when their permissions
are byte-for-byte identical, so a cache hit can never hand one role a figure computed under
another's visibility. That is why :meth:`DashboardScope.cache_key` exists and why every helper in
this module takes it as its first component.

An entry expires on read. Nothing sweeps, nothing reaps: a stale entry is simply never returned,
and the bounded eviction below is about memory, not correctness.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class CachedValue:
    value: Any
    expires_at: float
    stored_at: float


class TTLCache:
    def __init__(self, *, ttl_seconds: int, max_entries: int) -> None:
        self._ttl = max(0, ttl_seconds)
        self._max_entries = max(1, max_entries)
        self._entries: OrderedDict[str, CachedValue] = OrderedDict()
        self.hits = 0
        self.misses = 0

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def get(self, key: str, *, now: float | None = None) -> CachedValue | None:
        moment = time.monotonic() if now is None else now
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        if entry.expires_at <= moment:
            # Expired entries are dropped on the read that found them, so a key nobody asks for
            # again costs one dictionary slot until eviction and nothing else.
            self._entries.pop(key, None)
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return entry

    def set(self, key: str, value: Any, *, now: float | None = None) -> CachedValue:
        moment = time.monotonic() if now is None else now
        entry = CachedValue(value=value, expires_at=moment + self._ttl, stored_at=moment)
        self._entries[key] = entry
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return entry

    def clear(self) -> None:
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)


_cache = TTLCache(
    ttl_seconds=settings.DASHBOARD_CACHE_TTL_SECONDS,
    max_entries=settings.DASHBOARD_CACHE_MAX_ENTRIES,
)


def dashboard_cache() -> TTLCache:
    return _cache


def build_key(prefix: str, scope_key: str, *parts: Any) -> str:
    """One key format for every aggregate, with the scope always in front of the parameters."""
    rendered = "&".join("" if part is None else str(part) for part in parts)
    return f"{prefix}::{scope_key}::{rendered}"


def reset_for_ttl(ttl_seconds: int, max_entries: int | None = None) -> TTLCache:
    """Rebuild the process cache with a different TTL. Used by the suite, never at runtime."""
    global _cache
    _cache = TTLCache(
        ttl_seconds=ttl_seconds,
        max_entries=max_entries or settings.DASHBOARD_CACHE_MAX_ENTRIES,
    )
    return _cache
