"""
Graph-based routing engine for stadium navigation.

Implements Dijkstra's shortest-path algorithm with dynamic edge re-weighting
based on live crowd density. When a zone is congested, its adjacent edges
receive a higher effective weight, naturally routing fans around bottlenecks.

Algorithm complexity:
  - Time: O((V + E) log V) using a binary min-heap (heapq)
  - Space: O(V) for the distance and predecessor maps
  - V ≈ 500 nodes, E ≈ 1,500 edges per stadium → ~18,000 operations
  - At 10ns per operation: ≈ 0.18ms — well under the 200ms SLA

Why Dijkstra over A*?
  - A* requires a geographic heuristic (admissible h(n)) but stadium
    coordinate precision is low indoors (GPS signal degradation).
  - Dijkstra guarantees optimality without heuristic assumptions.
  - For |V| = 500, the performance difference is negligible.
"""

from __future__ import annotations

import heapq
import math
from typing import Optional

import structlog

from app.domain.models.stadium import StadiumEdge, StadiumGraph, StadiumNode

logger = structlog.get_logger(__name__)

# Congestion multipliers: when a zone is HIGH/CRITICAL, its incident edge
# weights are multiplied to discourage routing through it.
_CONGESTION_MULTIPLIERS: dict[str, float] = {
    "low": 1.0,
    "moderate": 1.5,
    "high": 3.0,
    "critical": 10.0,  # Effectively blocks the zone (10× longer than alternatives)
}

# Represents an unreachable node
_INFINITY = float("inf")


class GraphRouter:
    """
    Stadium path-finding service.

    Single Responsibility: Compute shortest paths in a StadiumGraph.
    This class knows nothing about HTTP, databases, or GenAI — it operates
    purely on graph primitives.

    The congestion_weights parameter allows the calling service to inject
    dynamic weights without this class needing to know how they're computed
    (Dependency Inversion Principle).
    """

    def __init__(self, graph: StadiumGraph) -> None:
        """
        Args:
            graph: The stadium's adjacency-list graph representation.
        """
        self._graph = graph

    def find_route(
        self,
        origin_id: str,
        destination_id: str,
        congestion_levels: dict[str, str] | None = None,
        require_accessible: bool = False,
        avoid_zones: set[str] | None = None,
    ) -> list[str] | None:
        """
        Compute the lowest-cost path from origin to destination.

        Uses Dijkstra's algorithm with a binary min-heap. Edge weights are
        dynamically adjusted by current congestion levels before the search.

        Args:
            origin_id: Source node ID.
            destination_id: Target node ID.
            congestion_levels: Maps zone_id → congestion level string.
                               If None, all edges use base weights.
            require_accessible: If True, only traverse ADA-compliant edges.
            avoid_zones: Set of zone IDs to treat as impassable.

        Returns:
            Ordered list of zone IDs forming the path (inclusive of origin
            and destination), or None if no path exists.

        Raises:
            ValueError: If origin or destination node not found in graph.
        """
        if origin_id not in self._graph.nodes:
            raise ValueError(f"Origin node '{origin_id}' not in graph")
        if destination_id not in self._graph.nodes:
            raise ValueError(f"Destination node '{destination_id}' not in graph")

        if origin_id == destination_id:
            return [origin_id]

        congestion_levels = congestion_levels or {}
        avoid_zones = avoid_zones or set()

        # ── Dijkstra's Algorithm ─────────────────────────────────────────
        # dist[node] = current known shortest distance from origin to node
        dist: dict[str, float] = {node_id: _INFINITY for node_id in self._graph.nodes}
        dist[origin_id] = 0.0

        # prev[node] = predecessor node on the shortest path (for reconstruction)
        prev: dict[str, str | None] = {node_id: None for node_id in self._graph.nodes}

        # Min-heap: (distance, node_id)
        # We use a tuple so Python compares by distance first (O(log V) operations)
        heap: list[tuple[float, str]] = [(0.0, origin_id)]

        visited: set[str] = set()

        while heap:
            current_dist, current_id = heapq.heappop(heap)

            # Lazy deletion: skip if we've found a shorter path since this was added
            if current_id in visited:
                continue
            visited.add(current_id)

            # Early termination: found the destination
            if current_id == destination_id:
                break

            for edge in self._graph.get_neighbors(current_id):
                neighbor_id = edge.target_id

                # Hard constraints: skip blocked/inaccessible edges
                if neighbor_id in avoid_zones:
                    continue
                if require_accessible and not edge.is_accessible:
                    continue
                if neighbor_id in visited:
                    continue

                # Dynamic weight: base weight × congestion multiplier of the TARGET zone
                # We penalize entering a congested zone, not leaving it.
                neighbor_congestion = congestion_levels.get(neighbor_id, "low")
                multiplier = _CONGESTION_MULTIPLIERS.get(neighbor_congestion, 1.0)
                effective_weight = edge.base_weight_seconds * multiplier

                new_dist = current_dist + effective_weight
                if new_dist < dist[neighbor_id]:
                    dist[neighbor_id] = new_dist
                    prev[neighbor_id] = current_id
                    heapq.heappush(heap, (new_dist, neighbor_id))

        # ── Path Reconstruction ──────────────────────────────────────────
        if dist[destination_id] == _INFINITY:
            logger.warning(
                "no_route_found",
                origin=origin_id,
                destination=destination_id,
                graph_size=self._graph.node_count,
            )
            return None

        # Reconstruct path by following predecessors backwards
        path: list[str] = []
        current: str | None = destination_id
        while current is not None:
            path.append(current)
            current = prev[current]

        path.reverse()  # O(n) — necessary after back-traversal
        return path

    def compute_route_details(
        self,
        path: list[str],
        congestion_levels: dict[str, str] | None = None,
    ) -> tuple[float, float]:
        """
        Compute total distance (meters) and time (seconds) for a given path.

        Args:
            path: Ordered list of zone IDs.
            congestion_levels: Optional congestion map for adjusted times.

        Returns:
            Tuple of (total_distance_meters, total_time_seconds).
        """
        if len(path) < 2:
            return 0.0, 0.0

        congestion_levels = congestion_levels or {}
        total_time = 0.0
        total_distance = 0.0

        for i in range(len(path) - 1):
            source_id = path[i]
            target_id = path[i + 1]

            # Find the specific edge connecting these nodes
            edge = self._find_edge(source_id, target_id)
            if edge is None:
                continue

            congestion = congestion_levels.get(target_id, "low")
            multiplier = _CONGESTION_MULTIPLIERS.get(congestion, 1.0)
            total_time += edge.base_weight_seconds * multiplier

            # Approximate distance using node coordinates (haversine)
            source_node = self._graph.nodes[source_id]
            target_node = self._graph.nodes[target_id]
            total_distance += _haversine_distance(
                source_node.latitude, source_node.longitude,
                target_node.latitude, target_node.longitude,
            )

        return total_distance, total_time

    def _find_edge(self, source_id: str, target_id: str) -> StadiumEdge | None:
        """Find the edge between two adjacent nodes. O(degree) per node."""
        for edge in self._graph.get_neighbors(source_id):
            if edge.target_id == target_id:
                return edge
        return None


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two GPS coordinates in meters.

    Haversine formula is accurate to within 0.5% for distances under 20km
    (easily sufficient for stadium navigation at sub-100m scales).

    Args:
        lat1, lon1: Source coordinates in decimal degrees.
        lat2, lon2: Target coordinates in decimal degrees.

    Returns:
        Distance in meters.
    """
    R = 6_371_000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c
