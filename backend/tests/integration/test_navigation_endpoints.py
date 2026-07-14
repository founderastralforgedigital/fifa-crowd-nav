"""
tests/integration/test_navigation_endpoints.py — Integration tests for the navigation API.

These tests verify the full POST /api/v1/navigate request/response pipeline
including request validation, routing computation, and response schema.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


STADIUM = "metlife"


def _nav_payload(**kwargs) -> dict:
    defaults = {
        "stadium_id": STADIUM,
        "origin_zone_id": "GATE_N",
        "destination_zone_id": "EXIT_E",
        "language": "en",
        "accessibility": "standard",
    }
    defaults.update(kwargs)
    return defaults


class TestNavigationEndpointHappyPath:
    """Valid navigation requests."""

    def test_navigate_returns_200(self, app_client: TestClient):
        response = app_client.post("/api/v1/navigate", json=_nav_payload())
        assert response.status_code == 200

    def test_response_has_required_fields(self, app_client: TestClient):
        data = app_client.post("/api/v1/navigate", json=_nav_payload()).json()
        required = [
            "stadium_id", "origin_zone_id", "destination_zone_id",
            "language", "steps", "total_distance_meters",
            "total_estimated_seconds", "route_zone_ids", "is_crowd_optimized",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_route_starts_at_origin(self, app_client: TestClient):
        data = app_client.post("/api/v1/navigate", json=_nav_payload()).json()
        assert data["route_zone_ids"][0] == "GATE_N"

    def test_route_ends_at_destination(self, app_client: TestClient):
        data = app_client.post("/api/v1/navigate", json=_nav_payload()).json()
        assert data["route_zone_ids"][-1] == "EXIT_E"

    def test_steps_are_sequential(self, app_client: TestClient):
        data = app_client.post("/api/v1/navigate", json=_nav_payload()).json()
        for idx, step in enumerate(data["steps"], start=1):
            assert step["step_number"] == idx

    def test_all_supported_languages(self, app_client: TestClient):
        """Navigation must succeed for all 10 supported languages."""
        languages = ["en", "es", "fr", "pt", "ar", "zh", "de", "it", "ja", "ko"]
        for lang in languages:
            response = app_client.post("/api/v1/navigate", json=_nav_payload(language=lang))
            assert response.status_code == 200, f"Failed for language: {lang}"
            assert response.json()["language"] == lang

    def test_accessible_mode(self, app_client: TestClient):
        data = app_client.post(
            "/api/v1/navigate",
            json=_nav_payload(accessibility="accessible")
        ).json()
        assert data["accessibility"] == "accessible"
        # All steps must be accessible
        for step in data["steps"]:
            assert step["is_accessible_route"] is True


class TestNavigationEndpointValidation:
    """Request validation and error handling."""

    def test_unknown_stadium_returns_404(self, app_client: TestClient):
        response = app_client.post(
            "/api/v1/navigate",
            json=_nav_payload(stadium_id="fake_stadium_xyz")
        )
        assert response.status_code == 404

    def test_invalid_stadium_id_format_returns_422(self, app_client: TestClient):
        """Stadium ID with special characters must fail Pydantic validation."""
        response = app_client.post(
            "/api/v1/navigate",
            json=_nav_payload(stadium_id="../../etc/passwd")
        )
        assert response.status_code == 422

    def test_invalid_zone_id_format_returns_422(self, app_client: TestClient):
        response = app_client.post(
            "/api/v1/navigate",
            json=_nav_payload(origin_zone_id="'; DROP TABLE--")
        )
        assert response.status_code == 422

    def test_unsupported_language_returns_422(self, app_client: TestClient):
        response = app_client.post(
            "/api/v1/navigate",
            json=_nav_payload(language="xx")
        )
        assert response.status_code == 422

    def test_extra_body_fields_rejected(self, app_client: TestClient):
        """NavigationRequest uses Config(extra='forbid')."""
        payload = _nav_payload()
        payload["injected_field"] = "evil"
        response = app_client.post("/api/v1/navigate", json=payload)
        assert response.status_code == 422

    def test_missing_stadium_id_returns_422(self, app_client: TestClient):
        payload = {
            "origin_zone_id": "GATE_N",
            "destination_zone_id": "EXIT_E",
        }
        response = app_client.post("/api/v1/navigate", json=payload)
        assert response.status_code == 422

    def test_avoid_zones_respected(self, app_client: TestClient):
        """Avoid-listed zones must not appear in the route."""
        avoid = ["CONC_N_L0"]
        data = app_client.post(
            "/api/v1/navigate",
            json=_nav_payload(avoid_zone_ids=avoid)
        ).json()
        for zone_id in data["route_zone_ids"]:
            assert zone_id not in avoid, f"Avoided zone {zone_id} found in route"


class TestNavigationEndpointSecurity:
    """Security-focused tests."""

    def test_sql_injection_in_zone_id_blocked_by_pattern(self, app_client: TestClient):
        """Zone IDs must match strict alphanumeric pattern; SQL chars fail."""
        response = app_client.post(
            "/api/v1/navigate",
            json=_nav_payload(origin_zone_id="GATE; DROP TABLE--")
        )
        assert response.status_code == 422

    def test_very_long_stadium_id_rejected(self, app_client: TestClient):
        """Oversized IDs must be rejected by the pattern validator."""
        response = app_client.post(
            "/api/v1/navigate",
            json=_nav_payload(stadium_id="a" * 100)
        )
        assert response.status_code == 422

    def test_too_many_avoid_zones_rejected(self, app_client: TestClient):
        """avoid_zone_ids has max_length=20; exceeding it must be rejected."""
        avoid = [f"ZONE_{i:03d}" for i in range(25)]  # 25 zones > max 20
        response = app_client.post(
            "/api/v1/navigate",
            json=_nav_payload(avoid_zone_ids=avoid)
        )
        assert response.status_code == 422


class TestHealthEndpoint:
    """Tests for the /health liveness probe."""

    def test_health_returns_200(self, app_client: TestClient):
        response = app_client.get("/health")
        assert response.status_code == 200

    def test_health_response_has_status(self, app_client: TestClient):
        data = app_client.get("/health").json()
        assert data["status"] == "healthy"

    def test_health_response_has_uptime(self, app_client: TestClient):
        data = app_client.get("/health").json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0
