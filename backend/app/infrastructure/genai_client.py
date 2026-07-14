"""
Gemini API client wrapper for GenAI text generation.

Wraps google-generativeai SDK with:
  - Async support via asyncio.to_thread (SDK is synchronous)
  - Timeout handling (GenAI calls should not block indefinitely)
  - Structured error types for upstream handling
  - Safety settings to prevent harmful content from stadium navigation context
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmCategory, HarmBlockThreshold

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class GenAIError(Exception):
    """Raised when the GenAI API call fails or returns an invalid response."""


class GeminiClient:
    """
    Async wrapper around the Gemini generative AI SDK.

    The google-generativeai SDK is synchronous. We use asyncio.to_thread()
    to run it in a thread pool, keeping the main event loop non-blocking.
    This is preferable to using a dedicated async client because:
      1. The official async SDK (genai.AsyncGenerativeModel) is available
         but we wrap for consistent error handling.
      2. asyncio.to_thread handles backpressure via the thread pool limits.
    """

    def __init__(self) -> None:
        # Configure SDK with API key from environment (never hardcoded)
        genai.configure(api_key=settings.gemini_api_key)

        self._model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            generation_config=GenerationConfig(
                temperature=settings.gemini_temperature,
                max_output_tokens=settings.gemini_max_output_tokens,
                # top_p / top_k left at defaults for balanced coherence
            ),
            # Safety settings: block harmful content that has no place in
            # stadium navigation guidance
            safety_settings={
                HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            },
        )

    async def generate_text(self, prompt: str) -> str:
        """
        Generate text from a prompt using Gemini, asynchronously.

        Wraps the synchronous SDK call in asyncio.to_thread with a 10-second
        timeout. If Gemini is slow during peak FIFA traffic, we time out and
        fall back to static templates rather than blocking the request.

        Args:
            prompt: The structured navigation prompt.

        Returns:
            Generated text string.

        Raises:
            GenAIError: On API errors, empty responses, or timeouts.
        """
        try:
            # Run sync SDK call in thread pool — non-blocking for event loop
            response = await asyncio.wait_for(
                asyncio.to_thread(self._model.generate_content, prompt),
                timeout=10.0,  # Hard 10-second timeout for stadium SLA
            )

            if not response.text:
                raise GenAIError("Gemini returned an empty response (possible content block)")

            return response.text

        except asyncio.TimeoutError:
            logger.warning("gemini_api_timeout", timeout_seconds=10)
            raise GenAIError("Gemini API timed out")
        except Exception as exc:
            logger.error("gemini_api_error", error=str(exc))
            raise GenAIError(f"Gemini API error: {exc}") from exc
