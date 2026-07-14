"""
GenAI navigation service — Gemini-powered multilingual fan guidance.

This service bridges the computed graph route with a natural language
explanation delivered in the fan's preferred language. It:
  1. Checks Redis cache for a cached response (identical request within TTL).
  2. If cache miss: constructs a structured prompt and calls Gemini.
  3. Sanitizes and validates the LLM response.
  4. Falls back to static templated text if GenAI is unavailable.
  5. Stores the response in Redis for subsequent identical requests.

Caching rationale:
  During peak FIFA events (goal celebrations, half-time), thousands of fans
  in the same zone will request the same route in the same language.
  A 300-second cache means the same Gemini call serves potentially thousands
  of fans, reducing latency to <5ms (Redis lookup) vs ~1.5s (Gemini API call).
  Cache key includes: stadium_id + origin + destination + language + congested_zones_hash.

Security considerations:
  - All user-supplied values are validated before being inserted into prompts.
  - The prompt includes an explicit system instruction to refuse non-navigation requests.
  - GenAI output is sanitized with bleach before being returned to clients.
"""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

import structlog

from app.domain.models.navigation import (
    LocalizedNavigationResponse,
    NavigationRoute,
    SupportedLanguage,
)
from app.domain.models.crowd import CongestionLevel
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── Static fallback templates (used when GenAI is disabled or unavailable) ──
# These are pre-translated strings — no GenAI required for the fallback path.
_FALLBACK_TEMPLATES: dict[str, str] = {
    "en": (
        "Please follow the route shown. We are directing you to avoid crowded areas. "
        "Estimated travel time: {time} minutes."
    ),
    "es": (
        "Por favor siga la ruta indicada. Le dirigimos para evitar zonas congestionadas. "
        "Tiempo estimado: {time} minutos."
    ),
    "fr": (
        "Veuillez suivre le trajet indiqué. Nous vous guidons pour éviter les zones surpeuplées. "
        "Durée estimée: {time} minutes."
    ),
    "pt": (
        "Por favor siga o percurso indicado. Estamos a direcioná-lo para evitar zonas lotadas. "
        "Tempo estimado: {time} minutos."
    ),
    "ar": (
        "يرجى اتباع المسار المحدد. نوجهك لتجنب المناطق المزدحمة. "
        "الوقت المقدر: {time} دقيقة."
    ),
    "zh": (
        "请按照指定路线行走。我们正引导您避开拥挤区域。"
        "预计用时：{time} 分钟。"
    ),
}


class GenAIClientProtocol(Protocol):
    """
    Interface (Protocol) for the GenAI client dependency.

    Using a Protocol (structural subtyping) instead of an abstract base
    class allows us to mock this in tests without inheriting from a concrete
    class — true Dependency Inversion Principle at the type level.
    """

    async def generate_text(self, prompt: str) -> str:
        """Generate text from a prompt. May raise GenAIError."""
        ...


class CacheProtocol(Protocol):
    """Interface for the cache dependency."""

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...


class GenAINavigatorService:
    """
    Orchestrates GenAI-enhanced multilingual navigation guidance.

    This service is stateless and has no side effects beyond Redis caching.
    Constructor injection of the client and cache makes it fully testable.
    """

    def __init__(
        self,
        genai_client: GenAIClientProtocol,
        cache: CacheProtocol,
    ) -> None:
        """
        Args:
            genai_client: Async GenAI client (Gemini or mock).
            cache: Async cache client (Redis or mock).
        """
        self._genai = genai_client
        self._cache = cache

    async def generate_navigation_guidance(
        self,
        route: NavigationRoute,
        language: SupportedLanguage,
        crowded_zones: list[str],
    ) -> LocalizedNavigationResponse:
        """
        Generate localized navigation guidance for a computed route.

        Steps:
          1. Compute deterministic cache key.
          2. Check Redis cache → return hit if available.
          3. Build GenAI prompt → call Gemini → validate response.
          4. On GenAI failure → fall back to static template.
          5. Cache the result (success or fallback).

        Args:
            route: The pre-computed navigation route.
            language: Fan's preferred language.
            crowded_zones: Zone IDs currently at HIGH/CRITICAL congestion
                           (used to explain routing choices in the prompt).

        Returns:
            LocalizedNavigationResponse with GenAI or fallback guidance.
        """
        cache_key = self._build_cache_key(route, language, crowded_zones)

        # ── Cache Check ──────────────────────────────────────────────────
        cached_raw = await self._cache.get(cache_key)
        if cached_raw:
            logger.info("genai_cache_hit", cache_key=cache_key)
            cached_data = json.loads(cached_raw)
            return LocalizedNavigationResponse(
                route=route,
                language=language,
                genai_guidance=cached_data["guidance"],
                is_genai_response=cached_data["is_genai"],
                cache_hit=True,
            )

        # ── GenAI Generation ─────────────────────────────────────────────
        guidance_text: str
        is_genai_response = False

        if settings.enable_genai:
            try:
                prompt = self._build_prompt(route, language, crowded_zones)
                raw_response = await self._genai.generate_text(prompt)
                guidance_text = self._validate_genai_response(raw_response)
                is_genai_response = True
                logger.info(
                    "genai_response_received",
                    language=language.value,
                    response_length=len(guidance_text),
                )
            except Exception as exc:
                # Never let GenAI failure cascade to the user — degrade gracefully
                logger.error("genai_generation_failed", error=str(exc), exc_info=True)
                guidance_text = self._get_fallback(route, language)
        else:
            guidance_text = self._get_fallback(route, language)

        # ── Cache Store ──────────────────────────────────────────────────
        cache_payload = json.dumps(
            {"guidance": guidance_text, "is_genai": is_genai_response}
        )
        await self._cache.set(cache_key, cache_payload, ttl=settings.redis_genai_cache_ttl)

        return LocalizedNavigationResponse(
            route=route,
            language=language,
            genai_guidance=guidance_text,
            is_genai_response=is_genai_response,
            cache_hit=False,
        )

    def _build_prompt(
        self,
        route: NavigationRoute,
        language: SupportedLanguage,
        crowded_zones: list[str],
    ) -> str:
        """
        Construct a structured, injection-resistant prompt for Gemini.

        Prompt engineering decisions:
          - Explicit persona: "FIFA stadium navigation assistant" limits the
            model to relevant topics (prevents off-topic GenAI abuse).
          - Structured output format specified: prevents markdown artifacts
            in the fan-facing response.
          - Language requirement stated twice (in system + user turn) to ensure
            the model honors it even for non-Latin script languages (AR, ZH).
          - Crowded zones are passed as context so the model can EXPLAIN the
            routing choice — not just give directions — improving fan trust.

        Args:
            route: The computed navigation route.
            language: ISO 639-1 language code.
            crowded_zones: Zones being actively avoided.

        Returns:
            Structured prompt string for the Gemini API.
        """
        estimated_minutes = round(route.total_time_seconds / 60, 1)
        step_descriptions = " → ".join(
            f"{s.zone_id} ({s.instruction})" for s in route.steps[:5]
        )
        avoided_text = ", ".join(crowded_zones[:5]) if crowded_zones else "none"

        return f"""You are a friendly FIFA World Cup 2026 stadium navigation assistant.
Your role is ONLY to provide clear, reassuring navigation directions to fans.
Do NOT discuss anything other than stadium navigation and crowd safety.
Respond ONLY in language code: {language.value}
Keep your response under 100 words.
Do NOT use markdown, bullet points, or HTML.

Navigation context:
- Stadium: {route.stadium_id}
- Origin: {route.origin_zone_id}
- Destination: {route.destination_zone_id}
- Estimated time: {estimated_minutes} minutes
- Key route steps: {step_descriptions}
- Crowded areas being avoided: {avoided_text}
- Accessible route: {route.is_accessible_route}

Generate a friendly, clear navigation instruction in {language.value} that:
1. Tells the fan where to go (follow the first 2-3 steps clearly)
2. Briefly explains why this route was chosen (crowd avoidance)
3. Provides an estimated arrival time
4. If accessible route, mentions elevator/ramp availability"""

    def _validate_genai_response(self, response: str) -> str:
        """
        Validate and sanitize the raw GenAI response.

        Checks:
          - Non-empty (Gemini occasionally returns empty strings on refusals).
          - Not excessively long (guards against prompt injection attempts that
            try to get the model to output large amounts of data).
          - bleach sanitization strips any injected HTML/script tags.

        Args:
            response: Raw text from the GenAI API.

        Returns:
            Sanitized response string.

        Raises:
            ValueError: If the response fails validation.
        """
        import bleach

        if not response or len(response.strip()) < 10:
            raise ValueError("GenAI response is too short or empty")

        if len(response) > 1000:
            logger.warning(
                "genai_response_truncated",
                original_length=len(response),
            )
            response = response[:1000]

        return bleach.clean(response.strip(), tags=[], strip=True)

    def _get_fallback(self, route: NavigationRoute, language: SupportedLanguage) -> str:
        """
        Generate a static fallback navigation message.

        Used when GenAI is disabled or throws an exception. Ensures the
        routing system is always functional even without AI capability.
        """
        estimated_minutes = round(route.total_time_seconds / 60, 1)
        template = _FALLBACK_TEMPLATES.get(
            language.value,
            _FALLBACK_TEMPLATES["en"],  # English as ultimate fallback
        )
        return template.format(time=estimated_minutes)

    def _build_cache_key(
        self,
        route: NavigationRoute,
        language: SupportedLanguage,
        crowded_zones: list[str],
    ) -> str:
        """
        Construct a deterministic, collision-resistant cache key.

        Key components:
          - stadium_id + origin + destination: Uniquely identifies the route request.
          - language: Different languages produce different guidance text.
          - crowded_zones hash: Same route with different avoided zones gets
            different GenAI text (different explanation of why that route was chosen).
          - Prefix "genai_nav:" namespaces keys to avoid Redis key conflicts.

        Using SHA-256 of the crowded_zones list produces a compact, fixed-length
        component (vs. joining all zone IDs which could make keys very long).

        Returns:
            Cache key string (max ~100 chars).
        """
        zones_hash = hashlib.sha256(
            json.dumps(sorted(crowded_zones)).encode()
        ).hexdigest()[:12]  # First 12 hex chars = 48 bits of collision resistance

        return (
            f"genai_nav:{route.stadium_id}:{route.origin_zone_id}"
            f":{route.destination_zone_id}:{language.value}:{zones_hash}"
        )
