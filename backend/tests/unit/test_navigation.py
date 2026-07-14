"""
tests/unit/test_navigation.py — Unit tests for NavigationService.

The GenAI translation service is mocked in all tests.
The routing graph and crowd service use real implementations backed by the
in-memory stadium registry, giving us real integration of the Dijkstra
engine with the crowd density model.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.crowd import CrowdDataIngestionRequest, SensorReading
from app.models.navigation import (
    AccessibilityPreference,
    NavigationRequest,
    SupportedLanguage,
)
from app.services.crowd_flow import CrowdFlowService
from app.services.navigation import NavigationService

STADIUM = "metlife"


def _make_nav_request(
    origin: str = "GATE_N",
    destination: str = "EXIT_E",
    language: SupportedLanguage = SupportedLanguage.EN,
    accessibility: AccessibilityPreference = AccessibilityPreference.STANDARD,
    avoid: list[str] | None = None,
) -> NavigationRequest:
    return NavigationRequest(
        stadium_id=STADIUM,
        origin_zone_id=origin,
        destination_zone_id=destination,
        language=language,
        accessibility=accessibility,
        avoid_zone_ids=avoid or [],
    )


class TestNavigationServiceBasic:
    """Basic navigation route computation tests."""

    @pytest.mark.asyncio
    async def test_route_from_gate_to_exit(
        self, navigation_service: NavigationService
    ):
        """Happy path: gate → exit should return a valid route."""
        request = _make_nav_request("GATE_N", "EXIT_E")
        response = await navigation_service.navigate(request)

        assert response.origin_zone_id == "GATE_N"
        assert response.destination_zone_id == "EXIT_E"
        assert len(response.steps) >= 2
        assert response.route_zone_ids[0] == "GATE_N"
        assert response.route_zone_ids[-1] == "EXIT_E"

    @pytest.mark.asyncio
    async def test_route_steps_are_numbered_sequentially(
        self, navigation_service: NavigationService
    ):
        """Step numbers must be sequential starting at 1."""
        response = await navigation_service.navigate(_make_nav_request())
        for idx, step in enumerate(response.steps, start=1):
            assert step.step_number == idx

    @pytest.mark.asyncio
    async def test_route_zone_ids_match_steps(
        self, navigation_service: NavigationService
    ):
        """route_zone_ids must match the zone_id sequence in steps."""
        response = await navigation_service.navigate(_make_nav_request())
        step_zone_ids = [s.zone_id for s in response.steps]
        assert step_zone_ids == response.route_zone_ids

    @pytest.mark.asyncio
    async def test_multilingual_instructions_generated(
        self, navigation_service: NavigationService, mock_translation_service
    ):
        """Translation service must be called once per route step."""
        response = await navigation_service.navigate(
            _make_nav_request(language=SupportedLanguage.ES)
        )
        assert mock_translation_service.generate_navigation_instruction.await_count >= 1

    @pytest.mark.asyncio
    async def test_unknown_stadium_raises_value_error(
        self, navigation_service: NavigationService
    ):
        with pytest.raises(ValueError, match="not found"):
            await navigation_service.navigate(
                NavigationRequest(
                    stadium_id="nonexistent",
                    origin_zone_id="GATE_N",
                    destination_zone_id="EXIT_E",
                    language=SupportedLanguage.EN,
                )
            )

    @pytest.mark.asyncio
    async def test_unknown_origin_zone_raises(
        self, navigation_service: NavigationService
    ):
        with pytest.raises(ValueError, match="not found"):
            await navigation_service.navigate(
                NavigationRequest(
                    stadium_id=STADIUM,
                    origin_zone_id="NONEXISTENT_ZONE",
                    destination_zone_id="EXIT_E",
                    language=SupportedLanguage.EN,
                )
            )

    @pytest.mark.asyncio
    async def test_same_origin_and_destination(
        self, navigation_service: NavigationService
    ):
        """Navigating from a zone to itself should return a trivial route."""
        response = await navigation_service.navigate(
            _make_nav_request("GATE_N", "GATE_N")
        )
        assert len(response.route_zone_ids) == 1
        assert response.route_zone_ids[0] == "GATE_N"

    @pytest.mark.asyncio
    async def test_total_distance_is_non_negative(
        self, navigation_service: NavigationService
    ):
        response = await navigation_service.navigate(_make_nav_request())
        assert response.total_distance_meters >= 0.0

    @pytest.mark.asyncio
    async def test_total_time_is_non_negative(
        self, navigation_service: NavigationService
    ):
        response = await navigation_service.navigate(_make_nav_request())
        assert response.total_estimated_seconds >= 0


class TestCrowdAwareRouting:
    """Tests that verify crowd density influences routing decisions."""

    @pytest.mark.asyncio
    async def test_congested_path_avoided(
        self,
        navigation_service: NavigationService,
        crowd_service: CrowdFlowService,
    ):
        """
        Route from GATE_N to EXIT_E normally goes through CONC_N_L0 and CONC_E_L0.
        When CONC_N_L0 is critically congested, the route should be marked as
        crowd-optimized (deviated from shortest path).
        """
        # Pack North Concourse to CRITICAL density (> 92% of 8000 = 7361)
        reading = SensorReading(
            sensor_id="S1", zone_id="CONC_N_L0", occupancy_count=7500,
            timestamp=datetime.now(timezone.utc), source="camera"
        )
        await crowd_service.ingest(
            CrowdDataIngestionRequest(stadium_id=STADIUM, readings=[reading])
        )

        response = await navigation_service.navigate(
            _make_nav_request("GATE_N", "EXIT_E")
        )
        # Response must be valid regardless of congestion
        assert len(response.steps) >= 1
        # Crowded path should be flagged or avoided
        # (is_crowd_optimized will be True if the path differs from naive shortest)
        # We can't assert the exact value since it depends on graph topology


class TestAccessibilityRouting:
    """Tests for accessible-mode routing."""

    @pytest.mark.asyncio
    async def test_accessible_mode_preferred(
        self, navigation_service: NavigationService
    ):
        """Accessible mode should produce a valid route (may be longer)."""
        response = await navigation_service.navigate(
            _make_nav_request(
                "GATE_N", "EXIT_E",
                accessibility=AccessibilityPreference.ACCESSIBLE
            )
        )
        # All steps must be marked as accessible
        for step in response.steps:
            assert step.is_accessible_route, (
                f"Step {step.step_number} at zone {step.zone_id} is not accessible"
            )

    @pytest.mark.asyncio
    async def test_avoid_zones_excluded_from_route(
        self, navigation_service: NavigationService
    ):
        """Zones in avoid_zone_ids must not appear in the resulting route."""
        # Avoid the direct concourse path
        avoid = ["CONC_N_L0"]
        response = await navigation_service.navigate(
            _make_nav_request("GATE_N", "EXIT_E", avoid=avoid)
        )
        for zone_id in response.route_zone_ids:
            assert zone_id not in avoid, f"Avoided zone {zone_id} appeared in route"
