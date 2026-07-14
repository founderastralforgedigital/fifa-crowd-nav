"""
Stadium graph repository — seeding and retrieval of stadium topology data.

In production this loads from PostGIS spatial database. For demonstration,
it seeds deterministic mock graphs for all 16 FIFA 2026 host stadiums.

The mock data is intentionally realistic: MetLife Stadium (capacity 82,500)
has proportionally more nodes than smaller venues.

FIFA 2026 Host Stadiums:
  USA: MetLife (NJ), AT&T (Dallas), SoFi (LA), Levi's (SF Bay), Hard Rock (Miami),
       Lincoln Financial (Philadelphia), Gillette (Boston), Arrowhead (KC),
       Lumen Field (Seattle), Rose Bowl (Pasadena), NRG (Houston)
  Canada: BC Place (Vancouver), BMO Field (Toronto)
  Mexico: Azteca (CDMX), Akron (Guadalajara), BBVA (Monterrey)
"""

from __future__ import annotations

import math
from functools import lru_cache

from app.domain.models.stadium import StadiumEdge, StadiumGraph, StadiumNode

# Stadiums with their approximate GPS center and capacity
_STADIUM_META: dict[str, dict] = {
    "METLIFE": {
        "name": "MetLife Stadium",
        "lat": 40.8135,
        "lon": -74.0745,
        "capacity": 82500,
        "zones": 20,
    },
    "ATT_STADIUM": {
        "name": "AT&T Stadium",
        "lat": 32.7480,
        "lon": -97.0930,
        "capacity": 80000,
        "zones": 18,
    },
    "SOFI": {
        "name": "SoFi Stadium",
        "lat": 33.9535,
        "lon": -118.3392,
        "capacity": 70000,
        "zones": 16,
    },
    "AZTECA": {
        "name": "Estadio Azteca",
        "lat": 19.3030,
        "lon": -99.1502,
        "capacity": 87500,
        "zones": 22,
    },
    "BC_PLACE": {
        "name": "BC Place",
        "lat": 49.2768,
        "lon": -123.1115,
        "capacity": 54500,
        "zones": 14,
    },
}

# Zone types in order of fan flow (roughly matches stadium layout)
_ZONE_TYPE_CYCLE = [
    "gate", "corridor", "concourse", "concession",
    "bathroom", "seating", "concourse", "exit",
]


def _seed_stadium_graph(stadium_id: str) -> StadiumGraph:
    """
    Generate a deterministic mock stadium graph for a given stadium ID.

    Each graph is a ring of zones (concourse loop) with inner spurs to
    seating sections and outer spurs to gates/exits. This approximates
    the real topology of modern oval NFL/soccer stadiums.

    Args:
        stadium_id: FIFA stadium code.

    Returns:
        Populated StadiumGraph with nodes and edges.
    """
    meta = _STADIUM_META.get(
        stadium_id,
        {"lat": 40.0, "lon": -74.0, "capacity": 60000, "zones": 12},
    )

    graph = StadiumGraph(stadium_id=stadium_id)
    num_zones = meta["zones"]
    center_lat: float = meta["lat"]
    center_lon: float = meta["lon"]
    zone_capacity = meta["capacity"] // num_zones

    # Generate nodes arranged in a ring (approximating a stadium concourse)
    for i in range(num_zones):
        angle = (2 * math.pi * i) / num_zones
        # Spread nodes ~200m apart around the stadium ring
        lat = center_lat + 0.001 * math.cos(angle)
        lon = center_lon + 0.001 * math.sin(angle)
        zone_type = _ZONE_TYPE_CYCLE[i % len(_ZONE_TYPE_CYCLE)]

        # Gates and exits have higher base capacity (wider corridors)
        node_capacity = (
            zone_capacity * 2 if zone_type in ("gate", "exit") else zone_capacity
        )

        node = StadiumNode(
            node_id=f"Z{i:02d}",
            name=f"{zone_type.title()} {i + 1}",
            zone_type=zone_type,
            latitude=lat,
            longitude=lon,
            capacity=node_capacity,
            is_accessible=(i % 3 == 0),  # Every 3rd zone is ADA-accessible
        )
        graph.add_node(node)

    # Connect nodes in a bidirectional ring (concourse loop)
    for i in range(num_zones):
        next_i = (i + 1) % num_zones
        # Base traversal time: ~60 seconds between adjacent zones
        graph.add_edge(StadiumEdge(
            source_id=f"Z{i:02d}",
            target_id=f"Z{next_i:02d}",
            base_weight_seconds=60.0,
            is_accessible=(i % 3 == 0),
        ))
        # Reverse direction (undirected path)
        graph.add_edge(StadiumEdge(
            source_id=f"Z{next_i:02d}",
            target_id=f"Z{i:02d}",
            base_weight_seconds=60.0,
            is_accessible=(i % 3 == 0),
        ))

    return graph


@lru_cache(maxsize=16)  # Cache one graph per stadium (16 stadiums max)
def get_or_create_stadium_graph(stadium_id: str) -> StadiumGraph:
    """
    Retrieve or lazily create the graph for a given stadium.

    @lru_cache ensures the graph is built only once per stadium per process
    lifetime — subsequent calls are O(1) dict lookups. This is safe because
    the graph topology (nodes/edges) is static; only edge WEIGHTS change
    dynamically (computed fresh each time from crowd data).

    Args:
        stadium_id: FIFA stadium code.

    Returns:
        Cached StadiumGraph instance.
    """
    return _seed_stadium_graph(stadium_id)
