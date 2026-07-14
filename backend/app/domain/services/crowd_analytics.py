"""
Crowd analytics service — the predictive core of the FIFA 2026 system.

Responsibilities:
  1. Ingest raw sensor/ticketing data for a stadium.
  2. Score each zone with a congestion level.
  3. Predict future bottlenecks using event-driven heuristics.
  4. Broadcast the snapshot to Redis for WebSocket delivery.

Predictive model rationale:
  Rather than a full ML model (which requires training data and serving
  infrastructure that doesn't exist pre-tournament), we use a
  graph-propagation heuristic that models crowd "diffusion":
  - When a match event occurs (goal, half-time), a fan surge is predicted
    at zones connected to seating areas.
  - Surge propagates to adjacent zones with an exponential decay based on
    graph distance (zones 1 hop away see 80% of the surge, 2 hops: 40%, etc.)
  - This is equivalent to a Breadth-First diffusion on the graph — O(V+E).

  This approach provides actionable predictions within milliseconds and
  degrades gracefully to zero-prediction mode if graph data is unavailable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog

from app.domain.models.crowd import (
    BottleneckPrediction,
    CongestionLevel,
    StadiumCrowdSnapshot,
    ZoneDensity,
)
from app.domain.models.stadium import StadiumGraph

logger = structlog.get_logger(__name__)

# Surge events and their associated zone types that are primarily impacted.
# This encodes domain knowledge from FIFA stadium operations playbooks.
_EVENT_SURGE_TARGETS: dict[str, list[str]] = {
    "HALF_TIME": ["concession", "bathroom", "concourse"],
    "GOAL": ["seating", "concourse"],  # Fans rush to view replays / celebrate
    "FINAL_WHISTLE": ["exit", "gate", "corridor"],
    "MATCH_START": ["gate", "corridor", "seating"],
    "PRE_MATCH": ["gate", "concourse"],
}

_DIFFUSION_DECAY: float = 0.5  # Each graph hop reduces surge intensity by 50%
_PREDICTION_HORIZON: int = 15  # Default prediction window in minutes


class CrowdAnalyticsService:
    """
    Service for ingesting sensor data and generating crowd predictions.

    This is a pure domain service — it depends only on domain models and
    an injected graph. No HTTP, no database, no GenAI. This makes it
    trivially unit-testable.
    """

    def __init__(self, graph: StadiumGraph) -> None:
        """
        Args:
            graph: Stadium graph for topology-aware diffusion propagation.
        """
        self._graph = graph

    def compute_snapshot(
        self,
        stadium_id: str,
        match_id: UUID,
        raw_zone_counts: dict[str, int],
        zone_capacities: dict[str, int],
        match_event: str | None = None,
    ) -> StadiumCrowdSnapshot:
        """
        Compute a full stadium crowd snapshot from raw sensor readings.

        Args:
            stadium_id: FIFA stadium code.
            match_id: UUID of the current match.
            raw_zone_counts: Maps zone_id → current fan count.
            zone_capacities: Maps zone_id → maximum safe capacity.
            match_event: Optional current event (e.g., 'HALF_TIME', 'GOAL').

        Returns:
            A complete StadiumCrowdSnapshot with zones and predictions.
        """
        now = datetime.now(tz=UTC)

        # ── Step 1: Build ZoneDensity objects for all sensor zones ────────
        zones: list[ZoneDensity] = []
        for zone_id, count in raw_zone_counts.items():
            capacity = zone_capacities.get(zone_id, 1000)  # Default safe capacity

            # Sanity clamp: cap at 110% capacity (sensor lag tolerance)
            clamped_count = min(count, int(capacity * 1.1))
            if clamped_count != count:
                logger.warning(
                    "zone_count_clamped",
                    zone_id=zone_id,
                    original=count,
                    clamped=clamped_count,
                )

            zones.append(
                ZoneDensity(
                    zone_id=zone_id,
                    stadium_id=stadium_id,
                    current_count=clamped_count,
                    capacity=capacity,
                    timestamp=now,
                )
            )

        # ── Step 2: Current congestion map ───────────────────────────────
        congestion_map: dict[str, CongestionLevel] = {
            z.zone_id: z.congestion_level for z in zones
        }

        # ── Step 3: Predict bottlenecks ──────────────────────────────────
        bottlenecks = self._predict_bottlenecks(
            zones=zones,
            congestion_map=congestion_map,
            match_event=match_event,
            stadium_id=stadium_id,
            now=now,
        )

        # ── Step 4: Overall stadium congestion (highest zone level) ───────
        level_order = [
            CongestionLevel.LOW,
            CongestionLevel.MODERATE,
            CongestionLevel.HIGH,
            CongestionLevel.CRITICAL,
        ]
        overall = max(
            (z.congestion_level for z in zones),
            key=lambda lvl: level_order.index(lvl),
            default=CongestionLevel.LOW,
        )

        snapshot = StadiumCrowdSnapshot(
            stadium_id=stadium_id,
            match_id=match_id,
            snapshot_time=now,
            zones=zones,
            bottlenecks=bottlenecks,
            overall_congestion=overall,
        )

        logger.info(
            "crowd_snapshot_computed",
            stadium_id=stadium_id,
            zone_count=len(zones),
            critical_zones=len(snapshot.critical_zone_ids),
            overall_congestion=overall.value,
            match_event=match_event,
        )

        return snapshot

    def _predict_bottlenecks(
        self,
        zones: list[ZoneDensity],
        congestion_map: dict[str, CongestionLevel],
        match_event: str | None,
        stadium_id: str,
        now: datetime,
    ) -> list[BottleneckPrediction]:
        """
        Predict future bottlenecks using graph-diffusion heuristics.

        Algorithm:
          1. Identify "seed" zones — currently HIGH/CRITICAL or in the
             surge targets for the current match event.
          2. BFS-propagate the surge up to 2 graph hops with exponential decay.
          3. Zones whose predicted occupancy crosses a congestion threshold
             are emitted as BottleneckPrediction objects.

        Time complexity: O(V + E) — single BFS pass over the graph.

        Args:
            zones: Current zone density readings.
            congestion_map: Current congestion levels per zone.
            match_event: Optional triggering match event.
            stadium_id: For attaching to predictions.
            now: Current UTC timestamp.

        Returns:
            List of predicted bottleneck zones (may be empty).
        """
        # Seed zones: currently overcrowded
        seed_zone_ids: set[str] = {
            z.zone_id
            for z in zones
            if z.congestion_level in (CongestionLevel.HIGH, CongestionLevel.CRITICAL)
        }

        # Add event-driven seeds based on zone type
        if match_event and match_event in _EVENT_SURGE_TARGETS:
            surge_types = _EVENT_SURGE_TARGETS[match_event]
            for zone_id, node in self._graph.nodes.items():
                if node.zone_type in surge_types:
                    seed_zone_ids.add(zone_id)

        if not seed_zone_ids:
            return []

        # BFS diffusion: propagate surge intensity from seed zones
        # surge_scores[zone_id] = 0.0 to 1.0 (relative surge intensity)
        surge_scores: dict[str, float] = {zone_id: 1.0 for zone_id in seed_zone_ids}
        queue: list[tuple[str, float, int]] = [  # (zone_id, intensity, depth)
            (zone_id, 1.0, 0) for zone_id in seed_zone_ids
        ]
        visited: set[str] = set(seed_zone_ids)
        max_depth = 2  # Limit propagation to 2 hops (balances accuracy vs noise)

        while queue:
            current_id, intensity, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            for edge in self._graph.get_neighbors(current_id):
                neighbor_id = edge.target_id
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    propagated_intensity = intensity * _DIFFUSION_DECAY
                    surge_scores[neighbor_id] = propagated_intensity
                    queue.append((neighbor_id, propagated_intensity, depth + 1))

        # Convert surge scores to BottleneckPredictions
        predictions: list[BottleneckPrediction] = []
        for zone_id, surge in surge_scores.items():
            if surge < 0.3:
                continue  # Noise threshold — don't predict minor ripple effects

            # Map surge intensity to predicted congestion level
            if surge >= 0.8:
                predicted = CongestionLevel.CRITICAL
                confidence = 0.85
            elif surge >= 0.5:
                predicted = CongestionLevel.HIGH
                confidence = 0.75
            else:
                predicted = CongestionLevel.MODERATE
                confidence = 0.60

            predictions.append(
                BottleneckPrediction(
                    zone_id=zone_id,
                    stadium_id=stadium_id,
                    predicted_congestion=predicted,
                    confidence_score=confidence,
                    prediction_horizon_minutes=_PREDICTION_HORIZON,
                    predicted_at=now,
                    triggered_by=match_event or "CURRENT_DENSITY",
                )
            )

        return predictions
