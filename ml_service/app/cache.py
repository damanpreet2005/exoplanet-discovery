"""
Prediction cache, abstracted behind a small interface so an in-process cache
can be swapped for Redis or another distributed cache later without touching
callers. Starts as a simple in-process, bounded, TTL cache -- appropriate for
a single-process development/small-deployment setup and consistent with the
fact that nothing in this repository already depends on Redis.
"""
import hashlib
import json
import threading
import time
from typing import Protocol

from app.schemas import PredictionFeatures


class Cache(Protocol):
    def get(self, key: str) -> dict | None: ...
    def set(self, key: str, value: dict) -> None: ...


class InMemoryTTLCache:
    def __init__(self, max_size: int, ttl_seconds: int) -> None:
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: dict) -> None:
        with self._lock:
            if len(self._store) >= self._max_size and key not in self._store:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]
            self._store[key] = (time.monotonic() + self._ttl_seconds, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


def make_cache_key(features: PredictionFeatures) -> str:
    """Deterministic cache key derived from the validated, ordered input."""
    ordered = features.as_ordered_list()
    payload = json.dumps(ordered, sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
