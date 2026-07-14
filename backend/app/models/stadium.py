"""
models/stadium.py — Pydantic domain models for stadiums and zones.

FIFA 2026 comprises 16 host cities across USA, Canada, and Mexico,
with stadiums ranging from 40,000 to 92,000 capacity.

These models serve as the single source of truth for stadium data shapes,
used by both the API layer (request/response) and the business logic layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated
from pydantic import BaseModel, Field, field_validator


class Country(str, Enum):
    """FIFA 2026 host countries."""
    USA = "USA"
    CANADA = "CAN"
    MEXICO = "MEX"


class ZoneType(str, Enum):
    """
    Discrete stadium zone categories.

    Granular zone types enable the routing engine to apply
    different traversal weights (e.g., concession stands are slower).
    """
    GATE = "gate"
    CONCOURSE = "concourse"
    CONCESSION = "concession"
    SEATING = "seating"
    EXIT = "exit"
    EMERGENCY_EXIT = "emergency_exit"
    MEDICAL = "medical"
    RESTROOM = "restroom"
    TRANSPORT_HUB = "transport_hub"


class DensityLevel(str, Enum):
    """
    Human-readable crowd density classification.

    Thresholds are derived from SFPE (Society of Fire Protection Engineers)
    pedestrian flow standards:
      - LOW   : < 0.5 persons/m²  — free movement
      - MEDIUM: 0.5–1.0 persons/m² — minor congestion
      - HIGH  : 1.0–2.0 persons/m² — significant congestion
      - CRITICAL: > 2.0 persons/m² — evacuation trigger
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Coordinates(BaseModel):
    """GPS-style coordinates for zone centroid."""
    latitude: Annotated[float, Field(ge=-90.0, le=90.0)]
    longitude: Annotated[float, Field(ge=-180.0, le=180.0)]


class StadiumZone(BaseModel):
    """
    A discrete navigable zone within a stadium.

    Each zone is a node in the routing graph. Zones are connected by
    edges whose weights incorporate distance, current density, and
    accessibility factors (e.g., escalator vs. stairs vs. ramp).
    """
    zone_id: str = Field(..., pattern=r"^[A-Z0-9_]{3,20}$", description="Unique zone identifier")
    name: str = Field(..., min_length=2, max_length=100)
    zone_type: ZoneType
    floor_level: int = Field(..., ge=0, le=10, description="Floor 0 = ground level")
    capacity: int = Field(..., ge=0, description="Maximum safe occupancy")
    coordinates: Coordinates
    is_accessible: bool = Field(True, description="ADA/wheelchair accessible")
    adjacent_zone_ids: list[str] = Field(default_factory=list)


class Stadium(BaseModel):
    """
    Full stadium descriptor for a FIFA 2026 host venue.

    The 16 host cities span three countries and multiple time zones.
    City metadata is included to correctly localize timestamps for
    both match scheduling and crowd analytics display.
    """
    stadium_id: str = Field(..., pattern=r"^[a-z0-9_]{3,30}$")
    name: str = Field(..., min_length=2, max_length=200)
    city: str
    country: Country
    timezone: str = Field(..., description="IANA timezone, e.g. 'America/New_York'")
    capacity: int = Field(..., ge=20_000, le=110_000)
    zones: list[StadiumZone] = Field(default_factory=list)
    coordinates: Coordinates

    @field_validator("timezone")
    @classmethod
    def validate_iana_timezone(cls, v: str) -> str:
        """Basic IANA timezone format check (continent/city pattern)."""
        if "/" not in v:
            raise ValueError(f"timezone must be IANA format (e.g. 'America/Dallas'), got '{v}'")
        return v


class StadiumSummary(BaseModel):
    """
    Lightweight stadium descriptor for list responses.

    Omits the full zone graph to keep list responses O(1) in payload size
    regardless of zone count.
    """
    stadium_id: str
    name: str
    city: str
    country: Country
    capacity: int
