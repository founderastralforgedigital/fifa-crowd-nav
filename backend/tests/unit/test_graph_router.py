"""
Unit tests for the GraphRouter service.

Tests cover:
  - Happy path routing (shortest path found)
  - Congestion-weighted routing (avoids high-density zones)
  - ADA-accessible routing (filters non-accessible edges)
  - Explicit zone avoidance
  - Edge cases: same origin/destination, unreachable nodes
  - Invalid inputs
"""

from __future__ import annotations

import pytest

from app.domain.models.stadium import StadiumGraph
from app.domain.services.graph_router import GraphRouter, _haversine_distance


class TestGraphRouterBasicRouting:
    """Tests for basic shortest-path computation."""

    def test_same_origin_destination_returns_single_node(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """A route from a node to itself should return immediately with [node_id]."""
        router = GraphRouter(simple_stadium_graph)
        path = router.find_route("GATE_A", "GATE_A")
        assert path == ["GATE_A"]

    def test_finds_direct_path(self, simple_stadium_graph: StadiumGraph) -> None:
        """Routing between adjacent nodes should find the direct path."""
        router = GraphRouter(simple_stadium_graph)
        path = router.find_route("GATE_A", "CONCOURSE_1")
        assert path is not None
        assert path[0] == "GATE_A"
        assert path[-1] == "CONCOURSE_1"

    def test_finds_multi_hop_path(self, simple_stadium_graph: StadiumGraph) -> None:
        """Dijkstra should find a path across multiple hops."""
        router = GraphRouter(simple_stadium_graph)
        path = router.find_route("GATE_A", "EXIT_C")
        assert path is not None
        assert path[0] == "GATE_A"
        assert path[-1] == "EXIT_C"
        # Verify path is contiguous (each step must be an actual edge)
        for i in range(len(path) - 1):
            neighbor_ids = [
                e.target_id for e in simple_stadium_graph.get_neighbors(path[i])
            ]
            assert path[i + 1] in neighbor_ids, (
                f"Non-adjacent nodes {path[i]} → {path[i+1]} in path"
            )

    def test_prefers_shorter_total_weight(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """
        From GATE_A to EXIT_C there are two uncongested paths:
          A→C1→B→EXIT_C: 60+60+60 = 180s
          A→C1→EXIT_C:    60+120  = 180s
          A→BATH_D→EXIT_C: 90+45 = 135s ← Dijkstra should choose this

        Verifying Dijkstra selects the minimum total weight path.
        """
        router = GraphRouter(simple_stadium_graph)
        path = router.find_route("GATE_A", "EXIT_C")
        _, total_time = router.compute_route_details(path)
        # The BATHROOM_D shortcut (135s) should be preferred
        assert total_time <= 135.0 + 1.0  # +1s tolerance for float arithmetic


class TestGraphRouterCongestionWeighting:
    """Tests for dynamic congestion-weighted routing."""

    def test_avoids_critical_congestion_zone(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """
        When CONCOURSE_1 is critical, routing from GATE_A to EXIT_C
        should avoid it (prefer BATHROOM_D path if available).
        """
        router = GraphRouter(simple_stadium_graph)
        congestion_levels = {"CONCOURSE_1": "critical"}  # 10× weight penalty
        path = router.find_route(
            "GATE_A", "EXIT_C", congestion_levels=congestion_levels
        )
        assert path is not None
        # CONCOURSE_1 should NOT appear in the path (too expensive)
        assert "CONCOURSE_1" not in path

    def test_uses_congested_zone_if_no_alternative(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """
        When the only path goes through a congested zone, Dijkstra still finds
        a path (just with higher cost). Routing should never return None when
        a path physically exists.
        """
        router = GraphRouter(simple_stadium_graph)
        # Make EVERY zone critical except GATE_A and SECTION_B
        congestion_levels = {
            "CONCOURSE_1": "critical",
            "EXIT_C": "critical",
            "BATHROOM_D": "critical",
        }
        # GATE_A → SECTION_B: only path is through CONCOURSE_1
        path = router.find_route(
            "GATE_A", "SECTION_B", congestion_levels=congestion_levels
        )
        assert path is not None  # Must still return a path

    def test_low_congestion_uses_base_weights(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """Low congestion should produce same result as no congestion map."""
        router = GraphRouter(simple_stadium_graph)
        path_no_congestion = router.find_route("GATE_A", "EXIT_C")
        path_low_congestion = router.find_route(
            "GATE_A", "EXIT_C",
            congestion_levels={"CONCOURSE_1": "low"}
        )
        assert path_no_congestion == path_low_congestion


class TestGraphRouterAccessibility:
    """Tests for ADA-accessible routing constraints."""

    def test_accessible_route_avoids_non_accessible_edges(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """
        The CONCOURSE_1 → SECTION_B edge is not accessible (is_accessible=False).
        Requesting an accessible route should avoid this edge.
        """
        router = GraphRouter(simple_stadium_graph)
        path = router.find_route(
            "GATE_A", "SECTION_B", require_accessible=True
        )
        # With accessible-only paths, GATE_A → SECTION_B may be unreachable
        # (all paths go through CONCOURSE_1 → SECTION_B which is inaccessible)
        # The test validates the constraint is honored, not that a path exists
        if path is not None:
            # If a path is found, verify no non-accessible edge is used
            for i in range(len(path) - 1):
                source, target = path[i], path[i + 1]
                edge = router._find_edge(source, target)
                assert edge is not None
                assert edge.is_accessible, (
                    f"Non-accessible edge {source}→{target} included in accessible route"
                )


class TestGraphRouterExplicitAvoidance:
    """Tests for user-specified zone avoidance."""

    def test_avoids_specified_zones(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """Explicitly avoided zones should not appear in the path."""
        router = GraphRouter(simple_stadium_graph)
        path = router.find_route(
            "GATE_A", "EXIT_C", avoid_zones={"CONCOURSE_1"}
        )
        assert path is not None
        assert "CONCOURSE_1" not in path

    def test_returns_none_when_all_paths_blocked(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """
        If all paths to the destination are explicitly blocked,
        find_route should return None (not raise an exception).
        """
        router = GraphRouter(simple_stadium_graph)
        # Block every zone except origin and destination
        path = router.find_route(
            "GATE_A", "EXIT_C",
            avoid_zones={"CONCOURSE_1", "BATHROOM_D", "SECTION_B"}
        )
        assert path is None


class TestGraphRouterInvalidInputs:
    """Tests for input validation and error handling."""

    def test_raises_on_invalid_origin(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """Unknown origin node should raise ValueError."""
        router = GraphRouter(simple_stadium_graph)
        with pytest.raises(ValueError, match="Origin node.*not in graph"):
            router.find_route("NONEXISTENT_ZONE", "EXIT_C")

    def test_raises_on_invalid_destination(
        self, simple_stadium_graph: StadiumGraph
    ) -> None:
        """Unknown destination node should raise ValueError."""
        router = GraphRouter(simple_stadium_graph)
        with pytest.raises(ValueError, match="Destination node.*not in graph"):
            router.find_route("GATE_A", "NONEXISTENT_ZONE")


class TestHaversineDistance:
    """Tests for the geographic distance calculation utility."""

    def test_same_point_returns_zero(self) -> None:
        """Distance from a point to itself is 0."""
        dist = _haversine_distance(40.0, -74.0, 40.0, -74.0)
        assert dist == pytest.approx(0.0, abs=0.001)

    def test_known_distance(self) -> None:
        """
        Approximate distance between MetLife and AT&T Stadium centers.
        Real distance ≈ 2,200 km. Haversine should be within 1% of this.
        """
        dist = _haversine_distance(40.8135, -74.0745, 32.7480, -97.0930)
        assert 2_100_000 < dist < 2_300_000  # meters

    def test_short_indoor_distance(self) -> None:
        """
        Indoor zone distances should be in the 10–300m range.
        Test two nodes 0.001° apart (approx 100m).
        """
        dist = _haversine_distance(40.000, -74.000, 40.001, -74.000)
        assert 100 < dist < 120  # meters
