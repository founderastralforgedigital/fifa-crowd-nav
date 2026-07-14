"""
utils/graph.py — Weighted directed graph with Dijkstra's shortest-path algorithm.

This module implements the routing backbone of the navigation system.
Stadium zones are modeled as graph nodes; corridors/pathways are edges.
Edge weights combine:
  - Physical distance (meters)
  - Crowd density multiplier (1x–5x slowdown)
  - Accessibility penalty (stairs inaccessible to mobility-impaired fans)

Algorithm complexity:
  - Time:  O((V + E) log V) using a min-heap priority queue
  - Space: O(V + E) for the adjacency list and distance array

Why Dijkstra and not A*?
  We do not have reliable heuristic coordinates for all internal stadium
  zones (escalators, concourses, concessions), so Dijkstra's guarantees
  optimal shortest paths without heuristic drift. A* would be preferred
  if we had reliable Euclidean spatial data for all zones.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Optional


# ── Data Structures ───────────────────────────────────────────────────────────

@dataclass(order=True)
class _HeapNode:
    """
    Priority queue entry for Dijkstra's min-heap.

    Separating the sort key (cost) from the payload (node_id) avoids
    comparison on string types, which is ambiguous and can break heap ordering.
    """
    cost: float
    node_id: str = field(compare=False)


@dataclass
class Edge:
    """
    Directed edge between two zone nodes.

    base_weight: Physical traversal cost in seconds (distance / walk_speed)
    density_multiplier: Applied at routing time based on current crowd state
    is_accessible: False if this edge requires stairs/escalator
    """
    to_node: str
    base_weight: float          # seconds under free-flow conditions
    is_accessible: bool = True  # Can mobility-impaired fans use this edge?


# ── Graph Implementation ──────────────────────────────────────────────────────

class WeightedGraph:
    """
    Weighted directed graph representing a stadium's navigable topology.

    Nodes map to StadiumZone zone_ids.
    Edges are one-directional to model one-way corridors accurately.
    For bidirectional corridors, add edges in both directions explicitly.

    Usage:
        graph = WeightedGraph()
        graph.add_edge("GATE_A", "CONCOURSE_N", base_weight=45.0)
        graph.add_edge("CONCOURSE_N", "GATE_A", base_weight=45.0)

        density_overrides = {"CONCOURSE_N": 3.5}  # HIGH density — 3.5x slower
        path, cost = graph.shortest_path("GATE_A", "SEATING_SEC_114", density_overrides)
    """

    def __init__(self) -> None:
        # Adjacency list: node_id → list of outgoing edges
        # Using dict[str, list[Edge]] gives O(1) node lookup and O(deg(v)) edge iteration
        self._adj: dict[str, list[Edge]] = {}

    # ── Graph Construction ────────────────────────────────────────────────────

    def add_node(self, node_id: str) -> None:
        """Register a node. Safe to call multiple times (idempotent)."""
        if node_id not in self._adj:
            self._adj[node_id] = []

    def add_edge(
        self,
        from_node: str,
        to_node: str,
        base_weight: float,
        is_accessible: bool = True,
    ) -> None:
        """
        Add a directed edge from from_node to to_node.

        Implicitly creates nodes if they do not exist.

        Args:
            from_node:     Source zone ID.
            to_node:       Destination zone ID.
            base_weight:   Traversal time in seconds under free-flow conditions.
            is_accessible: Whether this path is ADA/mobility accessible.
        """
        if base_weight < 0:
            raise ValueError(f"Edge weight must be non-negative, got {base_weight}")
        self.add_node(from_node)
        self.add_node(to_node)
        self._adj[from_node].append(Edge(to_node=to_node, base_weight=base_weight, is_accessible=is_accessible))

    def node_count(self) -> int:
        """Return the number of nodes — O(1)."""
        return len(self._adj)

    def edge_count(self) -> int:
        """Return the total number of edges — O(V)."""
        return sum(len(edges) for edges in self._adj.values())

    # ── Pathfinding ───────────────────────────────────────────────────────────

    def shortest_path(
        self,
        source: str,
        target: str,
        density_multipliers: Optional[dict[str, float]] = None,
        accessible_only: bool = False,
        excluded_nodes: Optional[set[str]] = None,
    ) -> tuple[list[str], float]:
        """
        Find the least-cost path from source to target using Dijkstra's algorithm.

        Crowd-aware routing is achieved by applying density_multipliers to edge
        base weights at query time, without modifying the graph structure.
        This allows the same graph to serve multiple concurrent route queries
        with different density states without locks or copies.

        Args:
            source:              Starting zone ID.
            target:              Destination zone ID.
            density_multipliers: Map of zone_id → cost multiplier based on crowd.
                                 E.g., {"CONCOURSE_N": 3.5} inflates all outbound
                                 edges from CONCOURSE_N by 3.5x.
            accessible_only:     If True, skip non-accessible edges (stairs, etc.)
            excluded_nodes:      Zones to treat as impassable (closed, emergency).

        Returns:
            A tuple of (ordered list of zone IDs from source to target, total cost).
            Returns ([], math.inf) if no path exists.

        Time complexity:  O((V + E) log V)
        Space complexity: O(V) for distance array and predecessor map
        """
        if source not in self._adj:
            raise ValueError(f"Source node '{source}' not in graph")
        if target not in self._adj:
            raise ValueError(f"Target node '{target}' not in graph")

        density_multipliers = density_multipliers or {}
        excluded_nodes = excluded_nodes or set()

        # dist[node] = current best known cost to reach node from source
        dist: dict[str, float] = {node: math.inf for node in self._adj}
        dist[source] = 0.0

        # prev[node] = predecessor on the cheapest path found so far
        prev: dict[str, Optional[str]] = {node: None for node in self._adj}

        # Min-heap: (cost, node_id)
        heap: list[_HeapNode] = [_HeapNode(cost=0.0, node_id=source)]

        visited: set[str] = set()

        while heap:
            current = heapq.heappop(heap)

            # Skip stale heap entries (a node may be pushed multiple times
            # before its optimal cost is finalized)
            if current.node_id in visited:
                continue
            visited.add(current.node_id)

            # Early termination: we've found the optimal path to target
            if current.node_id == target:
                break

            for edge in self._adj.get(current.node_id, []):
                neighbor = edge.to_node

                # Skip excluded zones (e.g., emergency closures)
                if neighbor in excluded_nodes:
                    continue

                # Skip inaccessible edges if accessibility mode is on
                if accessible_only and not edge.is_accessible:
                    continue

                # Apply crowd density multiplier for the *destination* zone.
                # We inflate the cost of entering a congested zone, which
                # naturally steers the algorithm toward less crowded paths.
                multiplier = density_multipliers.get(neighbor, 1.0)
                new_cost = current.cost + (edge.base_weight * multiplier)

                if new_cost < dist[neighbor]:
                    dist[neighbor] = new_cost
                    prev[neighbor] = current.node_id
                    heapq.heappush(heap, _HeapNode(cost=new_cost, node_id=neighbor))

        # No path found
        if dist[target] == math.inf:
            return [], math.inf

        # Reconstruct path by walking backwards through the predecessor map
        path: list[str] = []
        cursor: Optional[str] = target
        while cursor is not None:
            path.append(cursor)
            cursor = prev[cursor]
        path.reverse()

        return path, dist[target]
