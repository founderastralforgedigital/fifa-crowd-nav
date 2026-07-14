"""
dependencies.py — FastAPI dependency injection container.

This module centralizes all dependency creation following the
Dependency Injection pattern. Services are created once (as singletons)
and injected into route handlers via FastAPI's Depends() mechanism.

Benefits:
  - Single place to wire up all service dependencies
  - Easy to swap implementations (e.g., InMemoryCache ↔ RedisCache)
  - Test overrides via app.dependency_overrides = {...}
"""

from __future__ import annotations

from functools import lru_cache
from typing import AsyncGenerator

import structlog

from app.services.cache import CacheService, InMemoryCacheService
from app.services.crowd_flow import CrowdFlowService
from app.services.genai_translation import GenAITranslationService
from app.services.navigation import NavigationService
from app.services.stadium_registry import StadiumRegistry

logger = structlog.get_logger(__name__)


# ── Singleton Instances ───────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_stadium_registry() -> StadiumRegistry:
    """
    Create the stadium registry singleton.

    lru_cache ensures this is called exactly once across the application
    lifecycle. The registry is immutable after creation.
    """
    logger.info("dependencies.stadium_registry.initializing")
    return StadiumRegistry()


@lru_cache(maxsize=1)
def get_cache_service() -> CacheService:
    """
    Create the cache service singleton.

    Production: Returns RedisCacheService (configured via REDIS_URL env var).
    Development/test: Returns InMemoryCacheService.

    The switch is controlled by the REDIS_URL environment variable.
    """
    from app.config import get_settings
    settings = get_settings()

    if settings.redis_url and settings.redis_url != "redis://localhost:6379/0":
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(
                settings.redis_url,
                password=settings.redis_password or None,
                decode_responses=True,
            )
            from app.services.cache import RedisCacheService
            logger.info("dependencies.cache.redis_connected", url=settings.redis_url)
            return RedisCacheService(client)
        except Exception as exc:
            logger.warning("dependencies.cache.redis_failed_fallback", error=str(exc))

    logger.info("dependencies.cache.using_in_memory")
    return InMemoryCacheService()


@lru_cache(maxsize=1)
def get_crowd_service() -> CrowdFlowService:
    """Create the crowd flow service singleton."""
    return CrowdFlowService(registry=get_stadium_registry())


@lru_cache(maxsize=1)
def get_translation_service() -> GenAITranslationService:
    """Create the GenAI translation service singleton."""
    return GenAITranslationService(cache=get_cache_service())


@lru_cache(maxsize=1)
def get_navigation_service() -> NavigationService:
    """Create the navigation service singleton."""
    return NavigationService(
        registry=get_stadium_registry(),
        crowd_service=get_crowd_service(),
        translation_service=get_translation_service(),
        cache=get_cache_service(),
    )
