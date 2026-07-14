"""
services/stadium_registry.py — In-memory registry of all FIFA 2026 host stadiums.

FIFA 2026 host cities:
  USA (11): New York/NJ, Los Angeles, Dallas, San Francisco, Miami,
            Seattle, Boston, Atlanta, Kansas City, Houston, Philadelphia
  Canada (2): Toronto, Vancouver
  Mexico (3): Mexico City, Guadalajara, Monterrey

Each stadium is pre-loaded with a zone graph representing gates, concourses,
seating sections, concessions, and exits. The graph topology is built once at
startup and cached in memory — zone topology doesn't change during a tournament.

This service follows the Repository pattern: the application layer never
queries raw data structures directly; it always goes through StadiumRegistry.
"""

from __future__ import annotations

from app.models.stadium import (
    Country, Coordinates, Stadium, StadiumSummary, StadiumZone, ZoneType
)
from app.utils.graph import WeightedGraph


def _build_default_zone_graph() -> tuple[list[StadiumZone], WeightedGraph]:
    """
    Build a representative zone list and routing graph for a generic FIFA stadium.

    A real deployment would load this from a GIS database or a stadium-specific
    configuration file. For this reference implementation, we define a topology
    representative of a modern 60,000-seat stadium with:
      - 4 entrance gates (N, S, E, W)
      - 2 north/south concourses per level
      - 8 concession clusters
      - 4 seating bowl entry points per level (2 levels)
      - 4 exit corridors leading to transport hubs

    Graph edge weights are in seconds of traversal time under free-flow conditions
    at a comfortable walking speed of ~1.2 m/s (SFPE pedestrian standard).
    """
    zones = [
        StadiumZone(zone_id="GATE_N", name="North Gate", zone_type=ZoneType.GATE, floor_level=0,
                    capacity=5000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_N_L0"]),
        StadiumZone(zone_id="GATE_S", name="South Gate", zone_type=ZoneType.GATE, floor_level=0,
                    capacity=5000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_S_L0"]),
        StadiumZone(zone_id="GATE_E", name="East Gate", zone_type=ZoneType.GATE, floor_level=0,
                    capacity=3000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_E_L0"]),
        StadiumZone(zone_id="GATE_W", name="West Gate", zone_type=ZoneType.GATE, floor_level=0,
                    capacity=3000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_W_L0"]),
        StadiumZone(zone_id="CONC_N_L0", name="North Concourse Level 0", zone_type=ZoneType.CONCOURSE,
                    floor_level=0, capacity=8000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONCESS_N", "SEAT_L0_N", "CONC_E_L0", "CONC_W_L0"]),
        StadiumZone(zone_id="CONC_S_L0", name="South Concourse Level 0", zone_type=ZoneType.CONCOURSE,
                    floor_level=0, capacity=8000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONCESS_S", "SEAT_L0_S", "CONC_E_L0", "CONC_W_L0"]),
        StadiumZone(zone_id="CONC_E_L0", name="East Concourse Level 0", zone_type=ZoneType.CONCOURSE,
                    floor_level=0, capacity=4000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONCESS_E", "SEAT_L0_E", "EXIT_E"]),
        StadiumZone(zone_id="CONC_W_L0", name="West Concourse Level 0", zone_type=ZoneType.CONCOURSE,
                    floor_level=0, capacity=4000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONCESS_W", "SEAT_L0_W", "EXIT_W"]),
        StadiumZone(zone_id="CONCESS_N", name="North Concessions", zone_type=ZoneType.CONCESSION,
                    floor_level=0, capacity=2000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_N_L0"]),
        StadiumZone(zone_id="CONCESS_S", name="South Concessions", zone_type=ZoneType.CONCESSION,
                    floor_level=0, capacity=2000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_S_L0"]),
        StadiumZone(zone_id="CONCESS_E", name="East Concessions", zone_type=ZoneType.CONCESSION,
                    floor_level=0, capacity=1500, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_E_L0"]),
        StadiumZone(zone_id="CONCESS_W", name="West Concessions", zone_type=ZoneType.CONCESSION,
                    floor_level=0, capacity=1500, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_W_L0"]),
        StadiumZone(zone_id="SEAT_L0_N", name="Seating Level 0 North", zone_type=ZoneType.SEATING,
                    floor_level=0, capacity=15000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_N_L0"]),
        StadiumZone(zone_id="SEAT_L0_S", name="Seating Level 0 South", zone_type=ZoneType.SEATING,
                    floor_level=0, capacity=15000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_S_L0"]),
        StadiumZone(zone_id="SEAT_L0_E", name="Seating Level 0 East", zone_type=ZoneType.CONCOURSE,
                    floor_level=0, capacity=10000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_E_L0"]),
        StadiumZone(zone_id="SEAT_L0_W", name="Seating Level 0 West", zone_type=ZoneType.CONCOURSE,
                    floor_level=0, capacity=10000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_W_L0"]),
        StadiumZone(zone_id="EXIT_N", name="North Exit — Transport Hub", zone_type=ZoneType.TRANSPORT_HUB,
                    floor_level=0, capacity=10000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=[]),
        StadiumZone(zone_id="EXIT_S", name="South Exit — Transport Hub", zone_type=ZoneType.TRANSPORT_HUB,
                    floor_level=0, capacity=10000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=[]),
        StadiumZone(zone_id="EXIT_E", name="East Exit — Bus/Subway", zone_type=ZoneType.TRANSPORT_HUB,
                    floor_level=0, capacity=6000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=[]),
        StadiumZone(zone_id="EXIT_W", name="West Exit — Parking", zone_type=ZoneType.TRANSPORT_HUB,
                    floor_level=0, capacity=6000, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=[]),
        StadiumZone(zone_id="MEDICAL_CTR", name="Medical Centre", zone_type=ZoneType.MEDICAL,
                    floor_level=0, capacity=50, coordinates=Coordinates(latitude=0.0, longitude=0.0),
                    is_accessible=True, adjacent_zone_ids=["CONC_N_L0"]),
    ]

    graph = WeightedGraph()
    # Bidirectional edges with base weights in seconds
    edges = [
        ("GATE_N", "CONC_N_L0", 60, True),
        ("CONC_N_L0", "GATE_N", 60, True),
        ("GATE_S", "CONC_S_L0", 60, True),
        ("CONC_S_L0", "GATE_S", 60, True),
        ("GATE_E", "CONC_E_L0", 45, True),
        ("CONC_E_L0", "GATE_E", 45, True),
        ("GATE_W", "CONC_W_L0", 45, True),
        ("CONC_W_L0", "GATE_W", 45, True),
        ("CONC_N_L0", "CONCESS_N", 30, True),
        ("CONCESS_N", "CONC_N_L0", 30, True),
        ("CONC_S_L0", "CONCESS_S", 30, True),
        ("CONCESS_S", "CONC_S_L0", 30, True),
        ("CONC_E_L0", "CONCESS_E", 20, True),
        ("CONCESS_E", "CONC_E_L0", 20, True),
        ("CONC_W_L0", "CONCESS_W", 20, True),
        ("CONCESS_W", "CONC_W_L0", 20, True),
        ("CONC_N_L0", "SEAT_L0_N", 90, True),
        ("SEAT_L0_N", "CONC_N_L0", 90, True),
        ("CONC_S_L0", "SEAT_L0_S", 90, True),
        ("SEAT_L0_S", "CONC_S_L0", 90, True),
        ("CONC_E_L0", "SEAT_L0_E", 75, True),
        ("SEAT_L0_E", "CONC_E_L0", 75, True),
        ("CONC_W_L0", "SEAT_L0_W", 75, True),
        ("SEAT_L0_W", "CONC_W_L0", 75, True),
        ("CONC_N_L0", "CONC_E_L0", 120, True),
        ("CONC_E_L0", "CONC_N_L0", 120, True),
        ("CONC_N_L0", "CONC_W_L0", 120, True),
        ("CONC_W_L0", "CONC_N_L0", 120, True),
        ("CONC_S_L0", "CONC_E_L0", 120, True),
        ("CONC_E_L0", "CONC_S_L0", 120, True),
        ("CONC_S_L0", "CONC_W_L0", 120, True),
        ("CONC_W_L0", "CONC_S_L0", 120, True),
        ("CONC_E_L0", "EXIT_E", 60, True),
        ("CONC_W_L0", "EXIT_W", 60, True),
        ("CONC_N_L0", "EXIT_N", 90, True),
        ("CONC_S_L0", "EXIT_S", 90, True),
        ("CONC_N_L0", "MEDICAL_CTR", 30, True),
        ("MEDICAL_CTR", "CONC_N_L0", 30, True),
    ]

    for from_node, to_node, weight, accessible in edges:
        graph.add_edge(from_node, to_node, base_weight=float(weight), is_accessible=accessible)

    return zones, graph


# ── FIFA 2026 Stadium Data ────────────────────────────────────────────────────

def _build_stadiums() -> dict[str, tuple[Stadium, WeightedGraph]]:
    """
    Build the full FIFA 2026 host stadium registry.

    Returns a dict mapping stadium_id → (Stadium, WeightedGraph).
    The graph is built once and reused across all requests (immutable topology).
    """
    default_zones, _ = _build_default_zone_graph()
    stadiums: dict[str, tuple[Stadium, WeightedGraph]] = {}

    definitions = [
        # ── USA ──────────────────────────────────────────────────────────────
        ("metlife", "MetLife Stadium", "East Rutherford, NJ", Country.USA, "America/New_York", 82_500),
        ("sofi",    "SoFi Stadium", "Los Angeles, CA", Country.USA, "America/Los_Angeles", 70_240),
        ("atandt",  "AT&T Stadium", "Arlington, TX", Country.USA, "America/Chicago", 80_000),
        ("levis",   "Levi's Stadium", "Santa Clara, CA", Country.USA, "America/Los_Angeles", 68_500),
        ("hardrock","Hard Rock Stadium", "Miami Gardens, FL", Country.USA, "America/New_York", 65_000),
        ("lumen",   "Lumen Field", "Seattle, WA", Country.USA, "America/Los_Angeles", 69_000),
        ("gillette","Gillette Stadium", "Foxborough, MA", Country.USA, "America/New_York", 65_878),
        ("mercedes","Mercedes-Benz Stadium", "Atlanta, GA", Country.USA, "America/New_York", 71_000),
        ("arrowhead","Arrowhead Stadium", "Kansas City, MO", Country.USA, "America/Chicago", 76_416),
        ("nrg",     "NRG Stadium", "Houston, TX", Country.USA, "America/Chicago", 72_220),
        ("lincoln", "Lincoln Financial Field", "Philadelphia, PA", Country.USA, "America/New_York", 69_796),
        # ── Canada ───────────────────────────────────────────────────────────
        ("bmo",     "BMO Field", "Toronto, ON", Country.CANADA, "America/Toronto", 45_400),
        ("bc_place","BC Place", "Vancouver, BC", Country.CANADA, "America/Vancouver", 54_500),
        # ── Mexico ───────────────────────────────────────────────────────────
        ("azteca",  "Estadio Azteca", "Mexico City", Country.MEXICO, "America/Mexico_City", 87_523),
        ("akron",   "Estadio Akron", "Guadalajara", Country.MEXICO, "America/Mexico_City", 49_850),
        ("bbva",    "Estadio BBVA", "Monterrey", Country.MEXICO, "America/Monterrey", 53_400),
    ]

    for sid, name, city, country, tz, cap in definitions:
        zones, graph = _build_default_zone_graph()
        stadium = Stadium(
            stadium_id=sid,
            name=name,
            city=city,
            country=country,
            timezone=tz,
            capacity=cap,
            zones=zones,
            coordinates=Coordinates(latitude=0.0, longitude=0.0),  # placeholder
        )
        stadiums[sid] = (stadium, graph)

    return stadiums


class StadiumRegistry:
    """
    Singleton registry for all FIFA 2026 host stadiums.

    Provides O(1) lookup by stadium_id for both the Stadium model
    and its associated WeightedGraph.
    """

    def __init__(self) -> None:
        self._stadiums: dict[str, tuple[Stadium, WeightedGraph]] = _build_stadiums()

    def get_stadium(self, stadium_id: str) -> Stadium | None:
        """Return Stadium model or None if not found."""
        entry = self._stadiums.get(stadium_id)
        return entry[0] if entry else None

    def get_graph(self, stadium_id: str) -> WeightedGraph | None:
        """Return the routing WeightedGraph for a stadium or None."""
        entry = self._stadiums.get(stadium_id)
        return entry[1] if entry else None

    def list_stadiums(self) -> list[StadiumSummary]:
        """Return lightweight summaries for all 16 host stadiums."""
        return [
            StadiumSummary(
                stadium_id=s.stadium_id,
                name=s.name,
                city=s.city,
                country=s.country,
                capacity=s.capacity,
            )
            for s, _ in self._stadiums.values()
        ]

    def stadium_exists(self, stadium_id: str) -> bool:
        """O(1) membership check."""
        return stadium_id in self._stadiums
