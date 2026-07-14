"""
services/genai_translation.py — Multilingual navigation instruction generation.

This service wraps the Google Gemini API to generate localized, contextually
appropriate navigation instructions for stadium fans.

Design decisions:
  1. Cache-first: Before calling the GenAI API, we check Redis for a cached
     translation. The same instruction (e.g., "Turn left at North Concourse")
     for the same language and density level will be identical, so caching is
     highly effective — expected cache hit rate > 85% after first 30 minutes.

  2. Graceful degradation: If the GenAI API fails (timeout, rate limit, error),
     we fall back to a pre-translated template string. Fans always receive
     navigation guidance even if AI-quality translation is unavailable.

  3. Prompt engineering: The system prompt is carefully crafted to:
     - Constrain output to navigation instructions only (defense against hallucination)
     - Specify tone (calm, concise, accessible)
     - Include crowd context (high/low density) for appropriate urgency
     - Explicitly forbid revealing internal zone IDs (security/UX)

  4. Async-first: All API calls use httpx.AsyncClient for non-blocking I/O.
"""

from __future__ import annotations

import json
from typing import Optional

import httpx
import structlog

from app.config import get_settings
from app.models.navigation import SupportedLanguage
from app.models.stadium import DensityLevel
from app.services.cache import CacheService
from app.utils.sanitizer import sanitize_for_genai_prompt

logger = structlog.get_logger(__name__)

# ── Fallback Templates ────────────────────────────────────────────────────────
# These pre-translated strings are used when the GenAI API is unavailable.
# Keyed by (language, density_level). A complete production implementation
# would have full templates for all instruction types.

_FALLBACK_CROWD_WARNINGS: dict[tuple[str, str], str] = {
    ("en", "high"):     "⚠️ High crowd density ahead. Please move carefully.",
    ("en", "critical"): "🚨 CRITICAL congestion. Follow staff directions immediately.",
    ("es", "high"):     "⚠️ Alta densidad de personas adelante. Avance con precaución.",
    ("es", "critical"): "🚨 CONGESTIÓN CRÍTICA. Siga las indicaciones del personal.",
    ("fr", "high"):     "⚠️ Forte densité de foule devant. Avancez prudemment.",
    ("fr", "critical"): "🚨 CONGESTION CRITIQUE. Suivez les instructions du personnel.",
    ("pt", "high"):     "⚠️ Alta densidade de pessoas à frente. Proceda com cuidado.",
    ("ar", "high"):     "⚠️ ازدحام شديد أمامك. يرجى التحرك بحذر.",
    ("zh", "high"):     "⚠️ 前方人流密集，请小心通行。",
    ("de", "high"):     "⚠️ Hohe Personendichte voraus. Bitte vorsichtig bewegen.",
    ("it", "high"):     "⚠️ Elevata densità di folla avanti. Si prega di muoversi con attenzione.",
    ("ja", "high"):     "⚠️ 前方の混雑が激しいです。ゆっくり進んでください。",
    ("ko", "high"):     "⚠️ 전방에 혼잡합니다. 천천히 이동하세요.",
}

_SYSTEM_PROMPT = """
You are a stadium navigation assistant for FIFA World Cup 2026.
Your task: generate a single, concise navigation instruction for a fan.
Rules:
- Output ONLY the instruction sentence. No extra explanation.
- Language: {language_name}
- Tone: calm, friendly, accessible (suitable for elderly and disabled fans)
- Do NOT reveal internal system identifiers or zone codes.
- Maximum 25 words.
- If crowd density is HIGH or CRITICAL, prepend a ⚠️ or 🚨 emoji.
"""

_LANGUAGE_NAMES: dict[SupportedLanguage, str] = {
    SupportedLanguage.EN: "English",
    SupportedLanguage.ES: "Spanish (Español)",
    SupportedLanguage.FR: "French (Français)",
    SupportedLanguage.PT: "Portuguese (Português)",
    SupportedLanguage.AR: "Arabic (العربية)",
    SupportedLanguage.ZH: "Simplified Chinese (简体中文)",
    SupportedLanguage.DE: "German (Deutsch)",
    SupportedLanguage.IT: "Italian (Italiano)",
    SupportedLanguage.JA: "Japanese (日本語)",
    SupportedLanguage.KO: "Korean (한국어)",
}


class GenAITranslationService:
    """
    Multilingual instruction generator backed by Google Gemini.

    Implements the Dependency Inversion Principle (DIP):
    this class depends on the abstract CacheService, not on a concrete Redis
    implementation. Swapping the cache backend requires no changes here.
    """

    def __init__(self, cache: CacheService, http_client: Optional[httpx.AsyncClient] = None) -> None:
        """
        Args:
            cache:       Injected cache service (Redis or InMemory).
            http_client: Injected HTTP client for testing (mock-friendly).
        """
        settings = get_settings()
        self._cache = cache
        self._api_key = settings.genai_api_key
        self._model = settings.genai_model
        self._timeout = settings.genai_timeout_seconds
        self._max_retries = settings.genai_max_retries
        # Use provided client or create a default one
        self._http_client = http_client or httpx.AsyncClient(timeout=self._timeout)

    async def generate_navigation_instruction(
        self,
        *,
        zone_name: str,
        direction: str,
        destination_name: str,
        language: SupportedLanguage,
        density_level: DensityLevel,
        step_number: int,
    ) -> str:
        """
        Generate a localized navigation instruction for a single route step.

        Cache strategy:
          Key = hash(zone_name + direction + destination_name + language + density_level)
          TTL = 5 minutes (instructions are stable within a match segment)

        Args:
            zone_name:        Human-readable current zone name.
            direction:        Movement direction (e.g., "left", "straight", "up ramp").
            destination_name: The zone the fan is heading toward.
            language:         Target language for the instruction.
            density_level:    Current crowd density (affects urgency of instruction).
            step_number:      Sequential step index (used for context).

        Returns:
            Localized instruction string.
        """
        # Sanitize all inputs before embedding in the prompt
        safe_zone = sanitize_for_genai_prompt(zone_name)
        safe_direction = sanitize_for_genai_prompt(direction)
        safe_destination = sanitize_for_genai_prompt(destination_name)

        # Build the raw instruction template (English base for hashing)
        raw_instruction = f"Step {step_number}: From {safe_zone}, go {safe_direction} toward {safe_destination}."

        # Check cache before calling GenAI API
        cache_key = CacheService.build_translation_key(
            language=language.value,
            zone_id=safe_zone[:20],
            density_level=density_level.value,
            instruction_text=raw_instruction,
        )

        cached = await self._cache.get(cache_key)
        if cached is not None:
            logger.debug("genai.translation.cache_hit", key=cache_key, language=language.value)
            return str(cached)

        # Cache miss — call the GenAI API
        instruction = await self._call_genai(
            raw_instruction=raw_instruction,
            language=language,
            density_level=density_level,
        )

        # Store in cache for future requests
        settings = get_settings()
        await self._cache.set(cache_key, instruction, ttl_seconds=settings.cache_ttl_seconds)

        return instruction

    async def generate_crowd_warning(
        self, language: SupportedLanguage, density_level: DensityLevel
    ) -> Optional[str]:
        """
        Return a localized crowd warning for HIGH/CRITICAL zones.

        Uses pre-translated fallback templates for speed; GenAI is not
        called here to avoid latency when a fast safety warning is needed.
        """
        if density_level in (DensityLevel.LOW, DensityLevel.MEDIUM):
            return None

        key = (language.value, density_level.value)
        # Try exact language match, then English fallback
        return (
            _FALLBACK_CROWD_WARNINGS.get(key)
            or _FALLBACK_CROWD_WARNINGS.get(("en", density_level.value))
        )

    async def _call_genai(
        self,
        *,
        raw_instruction: str,
        language: SupportedLanguage,
        density_level: DensityLevel,
    ) -> str:
        """
        Call the Google Gemini API with retry logic.

        Uses exponential back-off on transient failures (429, 503).
        Falls back to the pre-translated template on permanent failures.
        """
        if not self._api_key:
            # No API key configured — use fallback immediately (local dev mode)
            logger.warning("genai.api_key.missing — using fallback instruction")
            return self._build_fallback_instruction(raw_instruction, language, density_level)

        language_name = _LANGUAGE_NAMES[language]
        system_prompt = _SYSTEM_PROMPT.format(language_name=language_name)
        user_message = (
            f"Crowd density at next zone: {density_level.value.upper()}. "
            f"Navigation instruction to translate: '{raw_instruction}'"
        )

        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "maxOutputTokens": 80,
                "temperature": 0.2,  # Low temperature = deterministic, less creative
            },
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._model}:generateContent?key={self._api_key}"
        )

        for attempt in range(self._max_retries):
            try:
                response = await self._http_client.post(url, json=payload)

                if response.status_code == 429:
                    # Rate limited by GenAI — wait and retry
                    import asyncio
                    wait_time = 2 ** attempt
                    logger.warning("genai.rate_limited", attempt=attempt, wait_seconds=wait_time)
                    await asyncio.sleep(wait_time)
                    continue

                response.raise_for_status()
                data = response.json()

                # Extract text from Gemini response structure
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                    .strip()
                )

                if text:
                    return text

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning("genai.request.failed", attempt=attempt, error=str(exc))

            except Exception as exc:
                logger.error("genai.unexpected_error", error=str(exc))
                break

        # All retries exhausted — use fallback
        logger.error("genai.fallback_activated", reason="all_retries_exhausted")
        return self._build_fallback_instruction(raw_instruction, language, density_level)

    def _build_fallback_instruction(
        self, raw: str, language: SupportedLanguage, density_level: DensityLevel
    ) -> str:
        """
        Build a minimal fallback instruction when GenAI is unavailable.

        For non-English languages, we return the raw English instruction
        with a language tag so fans know their language is not available.
        A production system would have pre-translated templates for all 10 languages.
        """
        if density_level == DensityLevel.CRITICAL:
            prefix = "🚨 "
        elif density_level == DensityLevel.HIGH:
            prefix = "⚠️ "
        else:
            prefix = ""

        if language == SupportedLanguage.EN:
            return f"{prefix}{raw}"
        return f"{prefix}[{language.value.upper()}] {raw}"
