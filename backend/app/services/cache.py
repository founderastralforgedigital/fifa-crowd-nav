"""
services/cache.py — Async caching layer backed by Redis (or in-memory fallback).

This module implements the Interface Segregation Principle (ISP):
the CacheService protocol defines the contract; concrete implementations
(RedisCacheService, InMemoryCacheService) are injected via dependency injection.

In production: RedisCacheService connects to a Redis cluster.
In tests:      InMemoryCacheService provides a zero-dependency mock.

Cache key strategy for GenAI translations:
    Key format: "nav:trans:{lang}:{zone_id}:{density_level}:{instruction_hash}"
    TTL: 5 minutes (configurable via CACHE_TTL_SECONDS env var)

    We do NOT cache personalized routes (they depend on real-time density).
    We DO cache translated static instructions per zone/language/density combo,
    since these are idempotent and expensive to regenerate via GenAI API.

LRU eviction is handled by Redis (maxmemory-policy allkeys-lru).
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ── Abstract Protocol ─────────────────────────────────────────────────────────

class CacheService(ABC):
    """Abstract base class defining the cache service interface."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Retrieve a value by key. Returns None on cache miss."""

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Store a value with an expiry TTL in seconds."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Invalidate a single cache entry."""

    @abstractmethod
    async def flush_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching a glob pattern. Returns count deleted."""

    @staticmethod
    def build_translation_key(language: str, zone_id: str, density_level: str, instruction_text: str) -> str:
        """
        Build a deterministic cache key for a translated navigation instruction.

        We hash the instruction text rather than embedding it directly in the key
        to: (1) keep key lengths bounded, (2) avoid special-char escaping issues.
        """
        instruction_hash = hashlib.sha256(instruction_text.encode()).hexdigest()[:16]
        return f"nav:trans:{language}:{zone_id}:{density_level}:{instruction_hash}"

    @staticmethod
    def build_crowd_snapshot_key(stadium_id: str) -> str:
        """Cache key for a stadium crowd snapshot."""
        return f"crowd:snapshot:{stadium_id}"


# ── Redis Implementation ──────────────────────────────────────────────────────

class RedisCacheService(CacheService):
    """
    Production Redis-backed cache service.

    Uses the redis.asyncio client for non-blocking I/O.
    All values are JSON-serialized to ensure type-safe round-trips.
    """

    def __init__(self, redis_client: Any) -> None:
        """
        Args:
            redis_client: An initialized redis.asyncio.Redis client instance.
                          Passed in rather than created here to enable testing
                          without a real Redis connection.
        """
        self._redis = redis_client

    async def get(self, key: str) -> Optional[Any]:
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            # Cache failures must NEVER crash the application.
            # Log and return a cache miss to allow normal request flow.
            logger.warning("cache.get.failed", key=key, error=str(exc))
            return None

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        try:
            serialized = json.dumps(value, default=str)
            await self._redis.set(key, serialized, ex=ttl_seconds)
        except Exception as exc:
            logger.warning("cache.set.failed", key=key, error=str(exc))

    async def delete(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception as exc:
            logger.warning("cache.delete.failed", key=key, error=str(exc))

    async def flush_pattern(self, pattern: str) -> int:
        """
        Scan and delete all keys matching a glob pattern.

        Uses SCAN rather than KEYS to avoid blocking the Redis event loop
        on large keyspaces. O(N) where N is the number of keys scanned.
        """
        count = 0
        try:
            async for key in self._redis.scan_iter(match=pattern):
                await self._redis.delete(key)
                count += 1
        except Exception as exc:
            logger.warning("cache.flush_pattern.failed", pattern=pattern, error=str(exc))
        return count


# ── In-Memory Fallback (Dev + Tests) ─────────────────────────────────────────

class InMemoryCacheService(CacheService):
    """
    In-memory LRU cache for local development and unit testing.

    Implements LRU eviction to bound memory usage at MAX_SIZE entries.
    Not suitable for production (no persistence, no distributed invalidation).

    Time complexity:
        get: O(1) amortized
        set: O(1) amortized
        delete: O(1)
        flush_pattern: O(N) — full scan required without index
    """

    MAX_SIZE = 1_024  # bound memory usage

    def __init__(self) -> None:
        # OrderedDict maintains insertion order, enabling O(1) LRU via move_to_end
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()

    async def get(self, key: str) -> Optional[Any]:
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        # Move to end to mark as recently used (LRU update)
        self._store.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        expires_at = time.monotonic() + ttl_seconds
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (value, expires_at)
        # Evict oldest entry if we exceed MAX_SIZE
        if len(self._store) > self.MAX_SIZE:
            self._store.popitem(last=False)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def flush_pattern(self, pattern: str) -> int:
        """Naive glob-match without fnmatch to avoid import overhead."""
        import fnmatch
        keys_to_delete = [k for k in self._store if fnmatch.fnmatch(k, pattern)]
        for key in keys_to_delete:
            del self._store[key]
        return len(keys_to_delete)
