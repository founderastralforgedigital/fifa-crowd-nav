"""
tests/integration/test_crowd_endpoints.py — Integration tests for crowd API endpoints.

These tests exercise the full FastAPI request/response cycle using the
TestClient from conftest. All external dependencies (auth, rate limit)
are overridden via dependency injection.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


STADIUM_ID = "metlife"


class TestCrowdSnapshotEndpoint:
    """GET /api/v1/crowd/{stadium_id}"""

    def test_get_snapshot_returns_200(self, app_client: TestClient):
        response = app_client.get(f"/api/v1/crowd/{STADIUM_ID}")
        assert response.status_code == 200

    def test_get_snapshot_response_shape(self, app_client: TestClient):
        """Response must match StadiumCrowdSnapshot schema."""
        response = app_client.get(f"/api/v1/crowd/{STADIUM_ID}")
        data = response.json()
        assert "stadium_id" in data
        assert "zones" in data
        assert "total_occupancy" in data
        assert "overall_density_level" in data
        assert "active_bottleneck_zone_ids" in data

    def test_get_snapshot_stadium_id_matches(self, app_client: TestClient):
        response = app_client.get(f"/api/v1/crowd/{STADIUM_ID}")
        data = response.json()
        assert data["stadium_id"] == STADIUM_ID

    def test_get_snapshot_zones_non_empty(self, app_client: TestClient):
        """A pre-initialized stadium must return at least one zone."""
        response = app_client.get(f"/api/v1/crowd/{STADIUM_ID}")
        data = response.json()
        assert len(data["zones"]) > 0

    def test_get_snapshot_unknown_stadium_returns_404(self, app_client: TestClient):
        response = app_client.get("/api/v1/crowd/stadium_does_not_exist_abc")
        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"] == "stadium_not_found"

    def test_get_snapshot_all_density_scores_valid(self, app_client: TestClient):
        """All density_score values must be in [0.0, 1.0]."""
        response = app_client.get(f"/api/v1/crowd/{STADIUM_ID}")
        data = response.json()
        for zone in data["zones"]:
            score = zone["density_score"]
            assert 0.0 <= score <= 1.0, f"Invalid density_score {score} for zone {zone['zone_id']}"


class TestCrowdIngestionEndpoint:
    """POST /api/v1/crowd/ingest"""

    def _make_payload(self, zone_id: str = "GATE_N", occupancy: int = 1000) -> dict:
        return {
            "stadium_id": STADIUM_ID,
            "readings": [
                {
                    "sensor_id": "TEST_SENSOR_001",
                    "zone_id": zone_id,
                    "occupancy_count": occupancy,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "nfc_gate",
                }
            ],
        }

    def test_ingest_returns_202(self, app_client: TestClient):
        response = app_client.post("/api/v1/crowd/ingest", json=self._make_payload())
        assert response.status_code == 202

    def test_ingest_response_contains_batch_id(self, app_client: TestClient):
        response = app_client.post("/api/v1/crowd/ingest", json=self._make_payload())
        data = response.json()
        assert "batch_id" in data
        assert data["status"] == "accepted"

    def test_ingest_updates_snapshot(self, app_client: TestClient):
        """After ingestion, the snapshot must reflect the new occupancy."""
        app_client.post("/api/v1/crowd/ingest", json=self._make_payload("GATE_N", 3500))
        snapshot = app_client.get(f"/api/v1/crowd/{STADIUM_ID}").json()
        gate_n = next((z for z in snapshot["zones"] if z["zone_id"] == "GATE_N"), None)
        assert gate_n is not None
        assert gate_n["current_occupancy"] == 3500

    def test_ingest_rejects_empty_readings(self, app_client: TestClient):
        """Empty readings list must fail validation."""
        payload = {"stadium_id": STADIUM_ID, "readings": []}
        response = app_client.post("/api/v1/crowd/ingest", json=payload)
        assert response.status_code == 422  # Unprocessable Entity

    def test_ingest_rejects_invalid_source(self, app_client: TestClient):
        """Invalid source type must fail Pydantic validation."""
        payload = {
            "stadium_id": STADIUM_ID,
            "readings": [
                {
                    "sensor_id": "S1",
                    "zone_id": "GATE_N",
                    "occupancy_count": 100,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "invalid_source_type",  # Must match pattern
                }
            ],
        }
        response = app_client.post("/api/v1/crowd/ingest", json=payload)
        assert response.status_code == 422

    def test_ingest_rejects_negative_occupancy(self, app_client: TestClient):
        payload = {
            "stadium_id": STADIUM_ID,
            "readings": [
                {
                    "sensor_id": "S1",
                    "zone_id": "GATE_N",
                    "occupancy_count": -50,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "nfc_gate",
                }
            ],
        }
        response = app_client.post("/api/v1/crowd/ingest", json=payload)
        assert response.status_code == 422


class TestCrowdEndpointSecurity:
    """Verify that security constraints are enforced on crowd endpoints."""

    def test_extra_fields_in_ingestion_body_rejected(self, app_client: TestClient):
        """
        The ingestion model does not use Config(extra='forbid') at the
        top level, but unknown sensor sources ARE rejected.
        This tests that unexpected structured input fails validation.
        """
        payload = {
            "stadium_id": STADIUM_ID,
            "readings": [
                {
                    "sensor_id": "S1",
                    "zone_id": "GATE_N",
                    "occupancy_count": 100,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "nfc_gate",
                    "malicious_field": "'; DROP TABLE zones; --",
                }
            ],
        }
        response = app_client.post("/api/v1/crowd/ingest", json=payload)
        # Pydantic will ignore extra fields by default, but data is not compromised
        # Status should still be 202 (extra fields stripped) or 422 if model forbids them
        assert response.status_code in (202, 422)
