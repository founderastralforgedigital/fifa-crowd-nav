"""
services/crowd_flow.py — Predictive crowd analytics engine.

This service implements the predictive analytics layer of the platform.
It maintains a real-time crowd state model per stadium and exposes:

  1. Data Ingestion: Accepts batched sensor/ticketing readings and updates
     the in-memory density state for each zone.

  2. Snapshot Query: Returns the full crowd state for a stadium at the
     current moment, with computed density levels per zone.

  3. Bottleneck Prediction: Uses a linear extrapolation model to estimate
     density 15 minutes into the future. In production, this would be
     replaced by an LSTM time-series model trained on historical FIFA data.

Predictive Model (mock):
  - Baseline rate of change is computed from the last 2 ingestion timestamps.
  - rate_of_change = (current_density - prev_density) / elapsed_time
  - predicted_density_t+15 = current_density + (rate_of_change * 900s)
  - Clamped to [0.0, 1.0] range.

State storage:
  - Uses a dict[stadium_id, dict[zone_id, ZoneState]] spatial hash.
  - O(1) zone lookup; O(Z) snapshot generation where Z = number of zones.
  - In production: state would be persisted to Redis to survive restarts.
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

from app.models.crowd import (
    CrowdDataIngestionRequest,
    StadiumCrowdSnapshot,
    ZoneCrowdState,
)
from app.models.stadium import DensityLevel, StadiumZone
from app.services.stadium_registry import StadiumRegistry

logger = structlog.get_logger(__name__)

# Crowd density thresholds (persons / capacity ratio)
DENSITY_THRESHOLDS = {
    DensityLevel.LOW:      (0.0,  0.5),
    DensityLevel.MEDIUM:   (0.5,  0.75),
    DensityLevel.HIGH:     (0.75, 0.92),
    DensityLevel.CRITICAL: (0.92, 1.0),
}

# Weight multipliers applied to routing edges per density level
DENSITY_ROUTING_MULTIPLIERS: dict[DensityLevel, float] = {
    DensityLevel.LOW:      1.0,
    DensityLevel.MEDIUM:   1.8,
    DensityLevel.HIGH:     3.5,
    DensityLevel.CRITICAL: 8.0,  # Effectively blocked — reroute mandatory
}

BOTTLENECK_THRESHOLD = DensityLevel.HIGH  # Zones at HIGH+ are reported as bottlenecks


@dataclass
class _ZoneState:
    """Internal mutable state for a single zone."""
    zone_id: str
    zone_ref: StadiumZone
    current_occupancy: int = 0
    prev_occupancy: int = 0
    last_update_time: float = field(default_factory=time.monotonic)
    prev_update_time: float = field(default_factory=time.monotonic)


def _classify_density(density_score: float) -> DensityLevel:
    """
    Map a normalized density score [0, 1] to a DensityLevel.

    Uses threshold ranges rather than fixed cut-points to avoid
    rapid oscillation at boundaries (hysteresis not implemented here
    but recommended for production alerting).
    """
    for level, (low, high) in DENSITY_THRESHOLDS.items():
        if low <= density_score < high:
            return level
    return DensityLevel.CRITICAL


class CrowdFlowService:
    """
    Core crowd analytics engine.

    Follows the Single Responsibility Principle: this service ONLY manages
    crowd state. The routing decision belongs to NavigationService.

    Thread safety: asyncio is single-threaded; the in-memory state is safe
    without locks. If multi-threading is introduced, use asyncio.Lock.
    """

    def __init__(self, registry: StadiumRegistry) -> None:
        self._registry = registry
        # _state[stadium_id][zone_id] = _ZoneState
        self._state: dict[str, dict[str, _ZoneState]] = defaultdict(dict)
        self._initialize_all_stadiums()

    def _initialize_all_stadiums(self) -> None:
        """
        Pre-populate state for all 16 host stadiums with zero occupancy.

        This ensures the first snapshot query returns a valid (empty) result
        rather than raising a KeyError.
        """
        for summary in self._registry.list_stadiums():
            stadium = self._registry.get_stadium(summary.stadium_id)
            if stadium is None:
                continue
            for zone in stadium.zones:
                self._state[summary.stadium_id][zone.zone_id] = _ZoneState(
                    zone_id=zone.zone_id,
                    zone_ref=zone,
                    # Seed with low random occupancy to simulate a pre-event stadium
                    current_occupancy=random.randint(0, int(zone.capacity * 0.05)),
                )

    async def ingest(self, request: CrowdDataIngestionRequest) -> int:
        """
        Process a batch of sensor readings and update zone occupancy state.

        Aggregation strategy: For each zone, take the MAXIMUM reading within
        the batch. This conservative approach avoids underestimating density
        when sensors report slightly different counts for the same zone.

        Args:
            request: Validated ingestion request with up to 500 sensor readings.

        Returns:
            Number of zone states updated.

        Complexity: O(R) where R = len(request.readings)
        """
        stadium_id = request.stadium_id
        if not self._registry.stadium_exists(stadium_id):
            raise ValueError(f"Stadium '{stadium_id}' not found in registry")

        # Aggregate max occupancy per zone from this batch — O(R)
        max_by_zone: dict[str, int] = defaultdict(int)
        for reading in request.readings:
            if reading.occupancy_count > max_by_zone[reading.zone_id]:
                max_by_zone[reading.zone_id] = reading.occupancy_count

        updated = 0
        for zone_id, occupancy in max_by_zone.items():
            if zone_id not in self._state[stadium_id]:
                logger.warning("crowd.ingest.unknown_zone", stadium_id=stadium_id, zone_id=zone_id)
                continue

            state = self._state[stadium_id][zone_id]
            now = time.monotonic()
            # Shift current → prev before updating
            state.prev_occupancy = state.current_occupancy
            state.prev_update_time = state.last_update_time
            state.current_occupancy = min(occupancy, state.zone_ref.capacity)
            state.last_update_time = now
            updated += 1

        logger.info("crowd.ingest.complete", stadium_id=stadium_id, zones_updated=updated,
                    batch_id=request.batch_id)
        return updated

    def _predict_future_density(self, state: _ZoneState) -> DensityLevel:
        """
        Linear extrapolation of density 15 minutes into the future.

        Formula:
            rate = (current_density - prev_density) / elapsed_time
            predicted_score = current_score + rate * 900  (900s = 15min)

        This is deliberately simple (no ML model) to be transparent and
        debuggable in a live stadium operations context.
        """
        capacity = state.zone_ref.capacity
        if capacity == 0:
            return DensityLevel.LOW

        current_score = state.current_occupancy / capacity
        prev_score = state.prev_occupancy / capacity
        elapsed = state.last_update_time - state.prev_update_time

        if elapsed < 1.0:
            # Not enough time has passed to compute a meaningful rate
            return _classify_density(current_score)

        rate = (current_score - prev_score) / elapsed
        predicted_score = current_score + (rate * 900)
        predicted_score = max(0.0, min(1.0, predicted_score))

        return _classify_density(predicted_score)

    async def get_snapshot(self, stadium_id: str) -> StadiumCrowdSnapshot:
        """
        Build a full crowd snapshot for a stadium.

        Complexity: O(Z) where Z = number of zones per stadium (~20 for this model).

        Args:
            stadium_id: FIFA 2026 stadium identifier.

        Returns:
            StadiumCrowdSnapshot with per-zone density and bottleneck flags.

        Raises:
            ValueError: If stadium_id is not in the registry.
        """
        if not self._registry.stadium_exists(stadium_id):
            raise ValueError(f"Stadium '{stadium_id}' not found")

        zone_states = []
        bottleneck_ids: list[str] = []
        total_occupancy = 0
        total_capacity = 0

        for zone_id, state in self._state[stadium_id].items():
            capacity = state.zone_ref.capacity
            occupancy = state.current_occupancy
            density_score = occupancy / capacity if capacity > 0 else 0.0
            density_level = _classify_density(density_score)
            predicted = self._predict_future_density(state)

            # Bottleneck probability combines current density and trend
            bottleneck_prob = density_score * 0.7 + (
                0.3 if predicted in (DensityLevel.HIGH, DensityLevel.CRITICAL) else 0.0
            )

            zone_states.append(ZoneCrowdState(
                zone_id=zone_id,
                zone_name=state.zone_ref.name,
                current_occupancy=occupancy,
                capacity=capacity,
                density_score=round(density_score, 4),
                density_level=density_level,
                predicted_density_in_15min=predicted,
                bottleneck_probability=round(min(bottleneck_prob, 1.0), 4),
                last_updated=datetime.now(timezone.utc),
            ))

            if density_level in (DensityLevel.HIGH, DensityLevel.CRITICAL):
                bottleneck_ids.append(zone_id)

            total_occupancy += occupancy
            total_capacity += capacity

        overall_score = total_occupancy / total_capacity if total_capacity > 0 else 0.0
        overall_level = _classify_density(overall_score)

        return StadiumCrowdSnapshot(
            stadium_id=stadium_id,
            snapshot_timestamp=datetime.now(timezone.utc),
            total_occupancy=total_occupancy,
            total_capacity=total_capacity,
            overall_density_level=overall_level,
            zones=zone_states,
            active_bottleneck_zone_ids=bottleneck_ids,
        )

    def get_density_multipliers(self, stadium_id: str) -> dict[str, float]:
        """
        Compute routing edge-weight multipliers for all zones in a stadium.

        Called by NavigationService before each Dijkstra run to incorporate
        real-time crowd data into the routing decision.

        Returns: dict[zone_id, multiplier] — O(Z) time and space.
        """
        multipliers: dict[str, float] = {}
        for zone_id, state in self._state.get(stadium_id, {}).items():
            capacity = state.zone_ref.capacity
            score = state.current_occupancy / capacity if capacity > 0 else 0.0
            level = _classify_density(score)
            multipliers[zone_id] = DENSITY_ROUTING_MULTIPLIERS[level]
        return multipliers
