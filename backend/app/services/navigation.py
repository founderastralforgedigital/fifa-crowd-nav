"""
services/navigation.py — Graph-based crowd-aware routing service.

This service orchestrates the full navigation pipeline:
  1. Validate that origin and destination zones exist in the given stadium.
  2. Retrieve real-time crowd density multipliers from CrowdFlowService.
  3. Identify excluded zones (CRITICAL density — treated as blocked).
  4. Run Dijkstra's algorithm on the stadium zone graph.
  5. For each step in the resulting path, call GenAITranslationService to
     generate a localized instruction.
  6. Return a NavigationResponse with all step details.

The separation between NavigationService (orchestration) and WeightedGraph
(algorithm) upholds the Single Responsibility Principle (SRP): swapping
the routing algorithm (e.g., from Dijkstra to A*) requires no changes here.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import structlog

from app.models.navigation import (
    AccessibilityPreference,
    NavigationRequest,
    NavigationResponse,
    RouteStep,
    SupportedLanguage,
)
from app.models.stadium import DensityLevel
from app.services.cache import CacheService
from app.services.crowd_flow import CrowdFlowService, DENSITY_ROUTING_MULTIPLIERS
from app.services.genai_translation import GenAITranslationService
from app.services.stadium_registry import StadiumRegistry

logger = structlog.get_logger(__name__)

# Speed at which we map graph cost (seconds) to distance for display
# Assumes average pedestrian speed of 1.2 m/s (SFPE standard)
_WALK_SPEED_MPS = 1.2

# Density multiplier above which a zone is treated as "blocked" for routing
_BLOCK_MULTIPLIER = DENSITY_ROUTING_MULTIPLIERS[DensityLevel.CRITICAL]

# Direction vocabulary used to build instruction strings per step
_DIRECTION_WORDS = ["straight", "left", "right", "up the ramp", "down the ramp", "through the gate"]


def _infer_direction(from_zone: str, to_zone: str) -> str:
    """
    Infer a human-readable direction from zone topology.

    In production, this would use actual spatial coordinates (lat/lon) to
    compute a bearing. For this implementation, we derive a deterministic
    pseudo-direction from zone ID hashes to keep it mockable and testable.
    """
    # Use a deterministic hash of the edge to pick a direction word
    hash_val = hash(f"{from_zone}→{to_zone}") % len(_DIRECTION_WORDS)
    return _DIRECTION_WORDS[abs(hash_val)]


class NavigationService:
    """
    Stadium navigation orchestrator.

    Composes CrowdFlowService, GenAITranslationService, and WeightedGraph
    to produce full multilingual navigation responses.
    """

    def __init__(
        self,
        registry: StadiumRegistry,
        crowd_service: CrowdFlowService,
        translation_service: GenAITranslationService,
        cache: CacheService,
    ) -> None:
        self._registry = registry
        self._crowd = crowd_service
        self._translation = translation_service
        self._cache = cache

    async def navigate(self, request: NavigationRequest) -> NavigationResponse:
        """
        Compute a crowd-optimized, localized navigation route.

        Args:
            request: Validated NavigationRequest from the API layer.

        Returns:
            NavigationResponse with ordered localized steps.

        Raises:
            ValueError: If the stadium or zones are not found.
        """
        # ── 1. Resolve stadium and its graph ──────────────────────────────────
        if not self._registry.stadium_exists(request.stadium_id):
            raise ValueError(f"Stadium '{request.stadium_id}' not found")

        graph = self._registry.get_graph(request.stadium_id)
        stadium = self._registry.get_stadium(request.stadium_id)
        if graph is None or stadium is None:
            raise ValueError(f"Graph not available for stadium '{request.stadium_id}'")

        # Build a zone lookup for name resolution — O(Z)
        zone_lookup = {z.zone_id: z for z in stadium.zones}

        if request.origin_zone_id not in zone_lookup:
            raise ValueError(f"Origin zone '{request.origin_zone_id}' not found")
        if request.destination_zone_id not in zone_lookup:
            raise ValueError(f"Destination zone '{request.destination_zone_id}' not found")

        # ── 2. Get real-time density multipliers ──────────────────────────────
        density_multipliers = self._crowd.get_density_multipliers(request.stadium_id)

        # ── 3. Identify excluded (CRITICAL) zones ─────────────────────────────
        excluded_nodes: set[str] = {
            zone_id
            for zone_id, mult in density_multipliers.items()
            if mult >= _BLOCK_MULTIPLIER
        }
        # Always allow the origin and destination regardless of density
        # (fan is already there; destination is where they need to be)
        excluded_nodes.discard(request.origin_zone_id)
        excluded_nodes.discard(request.destination_zone_id)

        # Also exclude user-requested avoidance zones
        excluded_nodes.update(request.avoid_zone_ids)

        # ── 4. Run routing algorithm ──────────────────────────────────────────
        accessible_only = request.accessibility == AccessibilityPreference.ACCESSIBLE

        path, total_cost = graph.shortest_path(
            source=request.origin_zone_id,
            target=request.destination_zone_id,
            density_multipliers=density_multipliers,
            accessible_only=accessible_only,
            excluded_nodes=excluded_nodes,
        )

        if not path or total_cost == math.inf:
            raise ValueError(
                f"No navigable route from '{request.origin_zone_id}' to "
                f"'{request.destination_zone_id}'. Try disabling zone exclusions."
            )

        # ── 5. Determine if the route is crowd-optimized ──────────────────────
        # Compare with the "naive" shortest path (no density multipliers)
        naive_path, naive_cost = graph.shortest_path(
            source=request.origin_zone_id,
            target=request.destination_zone_id,
            accessible_only=accessible_only,
        )
        is_crowd_optimized = path != naive_path

        # ── 6. Build localized route steps ────────────────────────────────────
        steps: list[RouteStep] = []
        total_distance = 0.0

        for idx, zone_id in enumerate(path):
            zone = zone_lookup.get(zone_id)
            zone_name = zone.name if zone else zone_id
            is_accessible = zone.is_accessible if zone else True

            # Estimate traversal time for this step
            # If not the last step, look up the edge weight
            if idx < len(path) - 1:
                next_zone_id = path[idx + 1]
                multiplier = density_multipliers.get(next_zone_id, 1.0)
                # Base weight is approximately 60s per step (simplified)
                base_weight = 60.0
                step_cost = base_weight * multiplier
            else:
                step_cost = 0.0

            step_distance = step_cost * _WALK_SPEED_MPS
            total_distance += step_distance

            # Determine direction and destination name
            if idx < len(path) - 1:
                next_zone = zone_lookup.get(path[idx + 1])
                destination_name = next_zone.name if next_zone else path[idx + 1]
                direction = _infer_direction(zone_id, path[idx + 1])
            else:
                destination_name = zone_name
                direction = "arrive"

            # Get density level for this zone
            multiplier = density_multipliers.get(zone_id, 1.0)
            # Reverse-map multiplier to density level
            density_level = DensityLevel.LOW
            for level, mult in DENSITY_ROUTING_MULTIPLIERS.items():
                if mult <= multiplier:
                    density_level = level

            # Generate localized instruction via GenAI (or cache)
            instruction = await self._translation.generate_navigation_instruction(
                zone_name=zone_name,
                direction=direction,
                destination_name=destination_name,
                language=request.language,
                density_level=density_level,
                step_number=idx + 1,
            )

            # Generate crowd warning if zone is congested
            crowd_warning = await self._translation.generate_crowd_warning(
                language=request.language,
                density_level=density_level,
            )

            steps.append(RouteStep(
                step_number=idx + 1,
                zone_id=zone_id,
                zone_name=zone_name,
                instruction=instruction,
                estimated_seconds=int(step_cost),
                crowd_warning=crowd_warning,
                is_accessible_route=is_accessible,
            ))

        total_seconds = int(total_cost)

        logger.info(
            "navigation.route.computed",
            stadium_id=request.stadium_id,
            origin=request.origin_zone_id,
            destination=request.destination_zone_id,
            language=request.language.value,
            steps=len(steps),
            crowd_optimized=is_crowd_optimized,
        )

        return NavigationResponse(
            stadium_id=request.stadium_id,
            origin_zone_id=request.origin_zone_id,
            destination_zone_id=request.destination_zone_id,
            language=request.language,
            accessibility=request.accessibility,
            steps=steps,
            total_distance_meters=round(total_distance, 2),
            total_estimated_seconds=total_seconds,
            route_zone_ids=path,
            is_crowd_optimized=is_crowd_optimized,
            cache_hit=False,
        )
