"""
Stadium graph model for route planning.

Models a stadium as a weighted directed graph where:
  - Nodes (V) = zones (gates, corridors, exits, concessions, bathrooms)
  - Edges (E) = walkable paths between adjacent zones
  - Edge weight = estimated traversal time in seconds

This structure supports Dijkstra's algorithm for shortest-path routing,
and allows dynamic re-weighting based on live crowd density data.

FIFA 2026 scale: MetLife Stadium has ~60 entry gates, ~300 interior zones.
Graph size: |V| ≈ 500, |E| ≈ 1,500 per stadium.
Dijkstra with binary heap: O((V+E) log V) ≈ O(2,000 × 9) ≈ 18,000 ops.
This is well within the <200ms SLA for a single route computation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True, frozen=True)
class StadiumNode:
    """
    Immutable graph node representing a stadium zone.

    Using @dataclass(slots=True) reduces per-object memory by ~40% compared
    to a regular class (no __dict__ overhead). With 500 nodes per stadium and
    16 stadiums, this saves approximately 300KB of heap across the system.

    Using frozen=True makes nodes hashable (usable in sets/dict keys) and
    prevents accidental mutation.
    """

    node_id: str
    name: str
    zone_type: str  # 'gate' | 'corridor' | 'exit' | 'concession' | 'bathroom' | 'seating'
    latitude: float
    longitude: float
    capacity: int
    is_accessible: bool = True  # ADA-compliant path (wheelchair/stroller)


@dataclass(slots=True)
class StadiumEdge:
    """
    Directed weighted edge between two stadium nodes.

    base_weight_seconds: Baseline traversal time under uncongested conditions.
    This is multiplied by a congestion factor in the routing service before
    path finding, so the 'real' weight is dynamic.
    """

    source_id: str
    target_id: str
    base_weight_seconds: float  # Normal traversal time (seconds)
    is_accessible: bool = True   # Ramp/elevator available (ADA compliance)
    is_emergency_exit: bool = False


@dataclass
class StadiumGraph:
    """
    Adjacency-list graph representation of a single stadium.

    adjacency: Maps each node_id → list of outgoing edges.
    Adjacency list chosen over matrix because the graph is SPARSE
    (E ≈ 3V), making O(V+E) traversal far better than O(V²) for a matrix.
    """

    stadium_id: str
    nodes: dict[str, StadiumNode] = field(default_factory=dict)
    adjacency: dict[str, list[StadiumEdge]] = field(default_factory=dict)

    def add_node(self, node: StadiumNode) -> None:
        """Register a zone node. O(1) amortized dict insertion."""
        self.nodes[node.node_id] = node
        if node.node_id not in self.adjacency:
            self.adjacency[node.node_id] = []

    def add_edge(self, edge: StadiumEdge) -> None:
        """
        Add a directed edge to the adjacency list.
        For undirected paths, call this twice with source/target swapped.
        O(1) amortized.
        """
        if edge.source_id not in self.adjacency:
            self.adjacency[edge.source_id] = []
        self.adjacency[edge.source_id].append(edge)

    def get_neighbors(self, node_id: str) -> list[StadiumEdge]:
        """
        Retrieve outgoing edges for a given node.

        Args:
            node_id: The source node identifier.

        Returns:
            List of StadiumEdge objects, or empty list if no outgoing edges.
            O(1) dict lookup.
        """
        return self.adjacency.get(node_id, [])

    @property
    def node_count(self) -> int:
        """Number of nodes in the graph. O(1)."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Total number of directed edges. O(V) — one pass over adjacency."""
        return sum(len(edges) for edges in self.adjacency.values())
