"""
Navigation domain models.

These models represent routing requests, computed paths, and the
GenAI-enhanced navigation instructions delivered to fans.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator
import bleach


class SupportedLanguage(str, Enum):
    """
    Languages supported by the GenAI navigation system.
    FIFA 2026 covers fans from 48 nations — these six languages cover
    the primary native tongues of the largest attending fan populations.
    """
    ENGLISH = "en"
    SPANISH = "es"      # Host nation Mexico; largest fan base in USA
    FRENCH = "fr"       # Host nation Canada; Morocco, France fans
    PORTUGUESE = "pt"   # Brazil, Portugal fans
    ARABIC = "ar"       # Saudi Arabia, Morocco fans
    CHINESE = "zh"      # Chinese fans; expanding FIFA market


ALLOWED_LANGUAGES = {lang.value for lang in SupportedLanguage}


class RouteStep(BaseModel):
    """A single navigation instruction in a computed route."""

    step_index: int
    zone_id: str
    instruction: str = Field(
        ...,
        max_length=200,
        description="Human-readable navigation step (e.g., 'Turn left at Gate A')",
    )
    estimated_seconds: float = Field(
        ...,
        ge=0,
        description="Estimated time to traverse this step in seconds",
    )
    is_accessible_path: bool = True


class NavigationRoute(BaseModel):
    """
    A complete computed route from origin to destination.
    Contains both the raw path (zone IDs) and human-readable steps.
    """

    route_id: UUID = Field(default_factory=uuid4)
    origin_zone_id: str
    destination_zone_id: str
    stadium_id: str
    steps: list[RouteStep]
    total_distance_meters: float = Field(ge=0)
    total_time_seconds: float = Field(ge=0)
    avoids_zones: list[str] = Field(
        default_factory=list,
        description="Zone IDs deliberately avoided due to high congestion",
    )
    is_accessible_route: bool = True


class LocalizedNavigationResponse(BaseModel):
    """
    The final fan-facing navigation response enriched by the GenAI service.

    This combines the computed route with a GenAI-generated natural language
    description in the fan's preferred language. This is the primary response
    payload from the /navigation/route endpoint.
    """

    route: NavigationRoute
    language: SupportedLanguage
    genai_guidance: str = Field(
        ...,
        description=(
            "GenAI-generated friendly navigation description in the fan's language. "
            "Includes context about WHY the route was chosen (e.g., 'Gate A is "
            "currently less crowded than Gate B, so we are routing you there')."
        ),
    )
    is_genai_response: bool = Field(
        ...,
        description="False if GenAI was unavailable and fallback static text was used",
    )
    cache_hit: bool = False

    @field_validator("genai_guidance", mode="before")
    @classmethod
    def sanitize_genai_output(cls, v: str) -> str:
        """
        Sanitize GenAI-generated text before returning to clients.

        Even trusted GenAI APIs can occasionally produce content with
        HTML/script tags if prompt injection occurs. We strip all HTML
        as a defense-in-depth measure. This is especially important for
        RTL languages (Arabic) where encoding issues can arise.

        bleach.clean() strips all HTML tags when tags=[] and strip=True.
        """
        return bleach.clean(v, tags=[], strip=True)


class NavigationRequest(BaseModel):
    """
    Inbound navigation request from a fan's mobile device.

    Strict input validation prevents injection attacks on the stadium/zone
    ID fields, which are used in cache key construction and graph lookups.
    """

    stadium_id: str = Field(
        ...,
        pattern=r"^[A-Z_]{3,20}$",
        description="FIFA stadium code",
        examples=["METLIFE", "ATT_STADIUM", "SOFI"],
    )
    origin_zone_id: str = Field(
        ...,
        pattern=r"^[A-Z0-9_-]{2,32}$",
        description="Fan's current zone",
    )
    destination_zone_id: str = Field(
        ...,
        pattern=r"^[A-Z0-9_-]{2,32}$",
        description="Fan's desired destination zone",
    )
    language: SupportedLanguage = SupportedLanguage.ENGLISH
    require_accessible_route: bool = Field(
        default=False,
        description="If True, route only through ADA-compliant paths",
    )
    avoid_zones: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Optional list of zone IDs the fan explicitly wants to avoid",
    )
