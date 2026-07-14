"""
models/crowd.py — Pydantic models for crowd density data.

These models define the contract for:
  1. Inbound sensor/ticketing data ingestion (CrowdDataIngestionRequest)
  2. Computed crowd state per stadium zone (ZoneCrowdState)
  3. Full stadium crowd snapshot returned to clients (StadiumCrowdSnapshot)

Design note: We separate the raw ingestion model from the computed state model
to enforce a clear boundary between the data ingestion pipeline and the
analytics engine. This upholds the Single Responsibility Principle (SRP).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.stadium import DensityLevel


class SensorReading(BaseModel):
    """
    A single sensor/gate reading contributed by a physical device.

    Sources include:
    - NFC ticket scan gates (entry/exit)
    - Bluetooth beacon arrays (zone occupancy)
    - Overhead camera ML inference counts
    - Manual steward counts (for calibration)
    """
    sensor_id: str = Field(..., pattern=r"^[A-Z0-9_\-]{4,40}$")
    zone_id: str = Field(..., pattern=r"^[A-Z0-9_]{3,20}$")
    occupancy_count: Annotated[int, Field(ge=0, le=200_000)]
    timestamp: datetime
    source: str = Field(..., pattern=r"^(nfc_gate|beacon|camera|manual)$")


class CrowdDataIngestionRequest(BaseModel):
    """
    Batch ingestion payload from ticketing/sensor systems.

    Batch ingestion reduces HTTP overhead during peak traffic periods
    (e.g., 92,000 fans exiting SoFi Stadium simultaneously).

    Maximum batch size is enforced to prevent memory exhaustion on a
    single request — large ingestions should be chunked by the sender.
    """
    stadium_id: str = Field(..., pattern=r"^[a-z0-9_]{3,30}$")
    batch_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    readings: Annotated[list[SensorReading], Field(min_length=1, max_length=500)]
    ingestion_source: str = Field("ticketing_system", max_length=50)

    @field_validator("readings")
    @classmethod
    def validate_readings_timestamps(cls, readings: list[SensorReading]) -> list[SensorReading]:
        """
        Reject ingestion batches with readings spanning more than 5 minutes.

        Stale or replayed data can corrupt the real-time crowd model.
        The analytics engine expects temporally coherent batches.
        """
        if len(readings) < 2:
            return readings
        timestamps = [r.timestamp for r in readings]
        spread_seconds = (max(timestamps) - min(timestamps)).total_seconds()
        if spread_seconds > 300:
            raise ValueError(
                f"Reading timestamps span {spread_seconds:.0f}s; max allowed is 300s. "
                "Split into smaller batches."
            )
        return readings


class ZoneCrowdState(BaseModel):
    """
    Computed crowd density state for a single zone.

    The density_score (0.0–1.0) is normalized by zone capacity,
    enabling the routing engine to compare zones with different sizes.

    density_score = current_occupancy / capacity
    """
    zone_id: str
    zone_name: str
    current_occupancy: int = Field(..., ge=0)
    capacity: int = Field(..., ge=1)
    density_score: Annotated[float, Field(ge=0.0, le=1.0)]
    density_level: DensityLevel
    predicted_density_in_15min: DensityLevel
    bottleneck_probability: Annotated[float, Field(ge=0.0, le=1.0)]
    last_updated: datetime

    @model_validator(mode="after")
    def validate_occupancy_vs_capacity(self) -> "ZoneCrowdState":
        """Occupancy must never logically exceed capacity."""
        if self.current_occupancy > self.capacity:
            raise ValueError(
                f"occupancy {self.current_occupancy} exceeds capacity {self.capacity} "
                f"for zone {self.zone_id}"
            )
        return self


class StadiumCrowdSnapshot(BaseModel):
    """
    Full crowd snapshot for a stadium at a point in time.

    Returned by GET /api/v1/crowd/{stadium_id}. Clients poll this
    endpoint every 30 seconds for real-time updates.
    """
    stadium_id: str
    snapshot_timestamp: datetime
    total_occupancy: int
    total_capacity: int
    overall_density_level: DensityLevel
    zones: list[ZoneCrowdState]
    active_bottleneck_zone_ids: list[str] = Field(
        default_factory=list,
        description="Zones currently classified as HIGH or CRITICAL density"
    )
