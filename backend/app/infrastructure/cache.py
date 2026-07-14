"""
Async Redis cache abstraction layer.

Wraps the redis-py async client with a typed interface. By abstracting Redis
behind a class, we can:
  1. Swap the backend (e.g., Valkey, DragonflyDB) without touching service code.
  2. Mock it in tests with a dict-backed implementation.
  3. Add instrumentation (cache hit/miss metrics) in one place.

Connection pooling: redis-py manages a connection pool internally. The
`get_cache_client()` function returns a singleton via asyncio.Lock to
ensure the pool is initialized only once across all async workers.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# Module-level singleton — shared across all requests in the same process
_cache_client: aioredis.Redis | None = None
_init_lock = asyncio.Lock()


async def get_cache_client() -> aioredis.Redis:
    """
    Return the singleton async Redis client, initializing it if needed.

    Uses a double-check locking pattern with asyncio.Lock to prevent
    multiple coroutines from creating duplicate connection pools on startup.

    Returns:
        Configured async Redis client instance.
    """
    global _cache_client
    if _cache_client is None:
        async with _init_lock:
            if _cache_client is None:  # Re-check after acquiring lock
                _cache_client = aioredis.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    # Connection pool settings for FIFA 2026 scale:
                    # 50 max connections per worker process × 4 workers = 200 total
                    max_connections=50,
                    socket_timeout=5.0,
                    socket_connect_timeout=5.0,
                    retry_on_timeout=True,
                )
                logger.info("redis_pool_initialized", url_prefix=settings.redis_host)
    return _cache_client


class CacheClient:
    """
    High-level typed cache client used by domain services.

    Wraps the raw Redis client with JSON serialization and structured
    error handling. Domain services use this instead of raw Redis.
    """

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    async def ping(self) -> bool:
        """Verify Redis connectivity. Returns True on success."""
        result = await self._redis.ping()
        return bool(result)

    async def get(self, key: str) -> str | None:
        """
        Retrieve a string value by key.

        Returns:
            The stored string, or None if key not found / expired.
        """
        try:
            value: str | None = await self._redis.get(key)
            return value
        except Exception as exc:
            logger.error("cache_get_error", key=key, error=str(exc))
            return None  # Degrade gracefully — don't fail the request

    async def set(self, key: str, value: str, ttl: int) -> None:
        """
        Store a string value with an expiry TTL.

        Args:
            key: Redis key.
            value: String value to store.
            ttl: Time-to-live in seconds. Key auto-expires after TTL.
        """
        try:
            await self._redis.set(key, value, ex=ttl)
        except Exception as exc:
            logger.error("cache_set_error", key=key, error=str(exc))
            # Non-fatal: request continues without caching this result

    async def get_json(self, key: str) -> dict[str, Any] | None:
        """Retrieve and JSON-deserialize a stored value."""
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("cache_json_decode_error", key=key)
            return None

    async def set_json(self, key: str, value: dict[str, Any], ttl: int) -> None:
        """JSON-serialize and store a dict value."""
        await self.set(key, json.dumps(value), ttl)

    async def publish(self, channel: str, message: str) -> None:
        """
        Publish a message to a Redis pub/sub channel.
        Used for broadcasting crowd snapshots to WebSocket handlers.
        """
        try:
            await self._redis.publish(channel, message)
        except Exception as exc:
            logger.error("cache_publish_error", channel=channel, error=str(exc))

    async def aclose(self) -> None:
        """Gracefully close the Redis connection pool."""
        await self._redis.aclose()
