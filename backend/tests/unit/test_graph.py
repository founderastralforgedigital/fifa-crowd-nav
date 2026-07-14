"""
tests/unit/test_graph.py — Unit tests for the WeightedGraph routing engine.

These tests exercise the Dijkstra implementation in complete isolation —
no services, no FastAPI, no I/O. Pure algorithmic correctness.
"""

from __future__ import annotations

import math
import pytest

from app.utils.graph import WeightedGraph


class TestWeightedGraphConstruction:
    """Tests for graph construction and structural integrity."""

    def test_add_single_node(self):
        g = WeightedGraph()
        g.add_node("A")
        assert g.node_count() == 1
        assert g.edge_count() == 0

    def test_add_node_is_idempotent(self):
        """Adding the same node twice must not create duplicates."""
        g = WeightedGraph()
        g.add_node("A")
        g.add_node("A")
        assert g.node_count() == 1

    def test_add_edge_implicitly_creates_nodes(self):
        g = WeightedGraph()
        g.add_edge("X", "Y", base_weight=5.0)
        assert g.node_count() == 2
        assert g.edge_count() == 1

    def test_add_edge_rejects_negative_weight(self):
        g = WeightedGraph()
        with pytest.raises(ValueError, match="non-negative"):
            g.add_edge("A", "B", base_weight=-1.0)

    def test_directed_graph_not_symmetric(self):
        """A single add_edge call creates a directed edge, not bidirectional."""
        g = WeightedGraph()
        g.add_edge("A", "B", base_weight=10.0)
        # A→B exists, B→A does not
        path_ab, cost_ab = g.shortest_path("A", "B")
        assert path_ab == ["A", "B"]
        # B→A should fail (no path)
        path_ba, cost_ba = g.shortest_path("B", "A")
        assert path_ba == []
        assert cost_ba == math.inf


class TestDijkstraShortestPath:
    """Tests for the shortest path algorithm under various conditions."""

    def test_simple_shortest_path(self, simple_graph: WeightedGraph):
        """
        A→B→D costs 20; A→C→D costs 35.
        Dijkstra must choose A→B→D.
        """
        path, cost = simple_graph.shortest_path("A", "D")
        assert path == ["A", "B", "D"]
        assert cost == pytest.approx(20.0)

    def test_same_source_and_target(self, simple_graph: WeightedGraph):
        """Route from a zone to itself should return trivial single-node path."""
        path, cost = simple_graph.shortest_path("A", "A")
        assert path == ["A"]
        assert cost == pytest.approx(0.0)

    def test_unreachable_target_returns_empty(self, simple_graph: WeightedGraph):
        """No path from D back to A in this directed graph."""
        path, cost = simple_graph.shortest_path("D", "A")
        assert path == []
        assert cost == math.inf

    def test_unknown_source_raises(self, simple_graph: WeightedGraph):
        with pytest.raises(ValueError, match="Source node"):
            simple_graph.shortest_path("UNKNOWN", "A")

    def test_unknown_target_raises(self, simple_graph: WeightedGraph):
        with pytest.raises(ValueError, match="Target node"):
            simple_graph.shortest_path("A", "UNKNOWN")

    def test_density_multiplier_redirects_path(self, simple_graph: WeightedGraph):
        """
        Without density: A→B→D (cost 20) is shortest.
        With B multiplier=10: A→B→D costs 10 + (10*10)=110; A→C→D costs 35.
        Dijkstra should choose A→C→D when B is congested.
        """
        # B is critically congested
        density = {"B": 10.0}
        path, cost = simple_graph.shortest_path("A", "D", density_multipliers=density)
        assert path == ["A", "C", "D"]
        assert cost == pytest.approx(35.0)

    def test_excluded_node_is_bypassed(self, simple_graph: WeightedGraph):
        """Excluding node B should force the A→C→D path."""
        path, cost = simple_graph.shortest_path("A", "D", excluded_nodes={"B"})
        assert path == ["A", "C", "D"]
        assert cost == pytest.approx(35.0)

    def test_excluded_origin_is_still_used(self, simple_graph: WeightedGraph):
        """Origin must never be excluded even if in excluded_nodes set."""
        path, cost = simple_graph.shortest_path("A", "D", excluded_nodes={"A"})
        # A is the origin — route must still start from A
        assert path[0] == "A"

    def test_accessible_only_skips_inaccessible_edges(self):
        """Edges with is_accessible=False should be skipped in accessible mode."""
        g = WeightedGraph()
        # Direct route is inaccessible (stairs)
        g.add_edge("GATE", "SEAT", base_weight=30.0, is_accessible=False)
        # Longer accessible route via ramp
        g.add_edge("GATE", "RAMP", base_weight=60.0, is_accessible=True)
        g.add_edge("RAMP", "SEAT", base_weight=30.0, is_accessible=True)

        # Standard: takes stairs (direct, cheaper)
        path_std, cost_std = g.shortest_path("GATE", "SEAT", accessible_only=False)
        assert path_std == ["GATE", "SEAT"]
        assert cost_std == pytest.approx(30.0)

        # Accessible: must use ramp
        path_acc, cost_acc = g.shortest_path("GATE", "SEAT", accessible_only=True)
        assert path_acc == ["GATE", "RAMP", "SEAT"]
        assert cost_acc == pytest.approx(90.0)

    def test_all_paths_blocked_returns_empty(self, simple_graph: WeightedGraph):
        """When all intermediate nodes are excluded, no path should exist."""
        path, cost = simple_graph.shortest_path("A", "D", excluded_nodes={"B", "C"})
        assert path == []
        assert cost == math.inf

    def test_large_graph_performance(self):
        """
        Dijkstra should complete in reasonable time on a large graph.
        Creates a 1000-node chain — O((V+E) log V) should be fast.
        """
        import time
        g = WeightedGraph()
        n = 1000
        for i in range(n - 1):
            g.add_edge(str(i), str(i + 1), base_weight=1.0)
            g.add_edge(str(i + 1), str(i), base_weight=1.0)

        start = time.monotonic()
        path, cost = g.shortest_path("0", str(n - 1))
        elapsed = time.monotonic() - start

        assert len(path) == n
        assert cost == pytest.approx(float(n - 1))
        assert elapsed < 1.0, f"Dijkstra took {elapsed:.3f}s on {n} nodes — too slow"
