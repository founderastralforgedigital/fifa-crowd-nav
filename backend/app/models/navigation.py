"""
models/navigation.py — Pydantic models for fan navigation requests and responses.

The navigation system is the consumer-facing core of this platform.
A fan provides their current location (zone) and destination, and the system
returns a multilingual, accessibility-aware route avoiding bottlenecks.

Supported languages map to the primary FIFA 2026 fan demographics:
- EN (English)  — USA, UK, Australia
- ES (Spanish)  — Mexico, Spain, Argentina
- FR (French)   — France, Canada (Quebec)
- PT (Portuguese) — Brazil
- AR (Arabic)   — Saudi Arabia, Morocco, Qatar
- ZH (Chinese)  — China
- DE (German)   — Germany
- IT (Italian)  — Italy
- JA (Japanese) — Japan
- KO (Korean)   — South Korea
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated
from pydantic import BaseModel, Field


class SupportedLanguage(str, Enum):
    """ISO 639-1 language codes for all supported navigation languages."""
    EN = "en"
    ES = "es"
    FR = "fr"
    PT = "pt"
    AR = "ar"
    ZH = "zh"
    DE = "de"
    IT = "it"
    JA = "ja"
    KO = "ko"


class AccessibilityPreference(str, Enum):
    """
    Routing preference for accessibility needs.

    STANDARD   — fastest route, may include stairs
    ACCESSIBLE — avoids stairs; uses ramps/elevators only
    MEDICAL    — routes toward nearest medical station first
    """
    STANDARD = "standard"
    ACCESSIBLE = "accessible"
    MEDICAL = "medical"


class NavigationRequest(BaseModel):
    """
    Fan navigation request payload.

    The routing engine uses this to find the optimal path in the stadium
    zone graph, considering current crowd density and accessibility.
    """
    stadium_id: str = Field(..., pattern=r"^[a-z0-9_]{3,30}$")
    origin_zone_id: str = Field(..., pattern=r"^[A-Z0-9_]{3,20}$")
    destination_zone_id: str = Field(..., pattern=r"^[A-Z0-9_]{3,20}$")
    language: SupportedLanguage = SupportedLanguage.EN
    accessibility: AccessibilityPreference = AccessibilityPreference.STANDARD
    avoid_zone_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Optional list of zone IDs the fan wants to avoid (e.g., known closed gates)"
    )

    class Config:
        # Reject any extra fields to prevent parameter pollution
        extra = "forbid"


class RouteStep(BaseModel):
    """
    A single step in the navigation route.

    Steps are presented sequentially to the fan. Each step includes
    a translated instruction, distance estimate, and contextual metadata.
    """
    step_number: int = Field(..., ge=1)
    zone_id: str
    zone_name: str
    instruction: str = Field(..., description="GenAI-generated, localized instruction")
    estimated_seconds: int = Field(..., ge=0, description="Estimated traversal time for this step")
    crowd_warning: str | None = Field(None, description="Localized warning if zone is congested")
    is_accessible_route: bool


class NavigationResponse(BaseModel):
    """
    Complete navigation response with localized route steps.

    total_estimated_seconds accounts for crowd-induced slowdowns:
    a HIGH density zone has a 2x traversal time multiplier,
    CRITICAL zones have a 5x multiplier and trigger rerouting.
    """
    stadium_id: str
    origin_zone_id: str
    destination_zone_id: str
    language: SupportedLanguage
    accessibility: AccessibilityPreference
    steps: list[RouteStep]
    total_distance_meters: Annotated[float, Field(ge=0)]
    total_estimated_seconds: int = Field(..., ge=0)
    route_zone_ids: list[str] = Field(description="Ordered list of zone IDs traversed")
    is_crowd_optimized: bool = Field(
        description="True if the route deviates from shortest path to avoid congestion"
    )
    cache_hit: bool = Field(False, description="True if response was served from cache")
