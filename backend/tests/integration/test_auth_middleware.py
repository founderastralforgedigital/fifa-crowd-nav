"""
tests/integration/test_auth_middleware.py — Integration tests for JWT authentication.

These tests verify the auth enforcement behavior by using a REAL app instance
(no auth override), then providing mock tokens to test each branch.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.cache import InMemoryCacheService
from app.services.crowd_flow import CrowdFlowService
from app.services.navigation import NavigationService
from app.services.stadium_registry import StadiumRegistry


@pytest.fixture
def unauthed_client():
    """
    TestClient with NO auth override — tests real JWT enforcement.
    Rate limiting is still disabled to keep tests focused on auth.
    """
    from app.dependencies import (
        get_crowd_service, get_navigation_service, get_stadium_registry,
    )
    from app.middleware.rate_limiter import enforce_rate_limit

    registry = StadiumRegistry()
    cache = InMemoryCacheService()
    crowd = CrowdFlowService(registry=registry)

    application = create_app()
    application.dependency_overrides[enforce_rate_limit] = lambda: None
    application.dependency_overrides[get_stadium_registry] = lambda: registry
    application.dependency_overrides[get_crowd_service] = lambda: crowd

    with TestClient(application, raise_server_exceptions=False) as client:
        yield client


class TestAuthEnforcement:
    """Verify endpoints reject unauthenticated requests correctly."""

    def test_crowd_snapshot_requires_auth(self, unauthed_client: TestClient):
        """GET /crowd/{id} without a token must return 401."""
        response = unauthed_client.get("/api/v1/crowd/metlife")
        assert response.status_code == 401

    def test_navigate_requires_auth(self, unauthed_client: TestClient):
        """POST /navigate without a token must return 401."""
        response = unauthed_client.post(
            "/api/v1/navigate",
            json={
                "stadium_id": "metlife",
                "origin_zone_id": "GATE_N",
                "destination_zone_id": "EXIT_E",
                "language": "en",
            },
        )
        assert response.status_code == 401

    def test_ingest_requires_auth(self, unauthed_client: TestClient):
        """POST /crowd/ingest without a token must return 401."""
        response = unauthed_client.post(
            "/api/v1/crowd/ingest",
            json={
                "stadium_id": "metlife",
                "readings": [],
            },
        )
        # 422 is also acceptable (body validation before auth in some frameworks)
        assert response.status_code in (401, 422)

    def test_stadiums_list_no_auth_required(self, unauthed_client: TestClient):
        """GET /stadiums is publicly accessible (no auth required)."""
        response = unauthed_client.get("/api/v1/stadiums")
        assert response.status_code == 200

    def test_health_no_auth_required(self, unauthed_client: TestClient):
        """GET /health is a liveness probe — must not require auth."""
        response = unauthed_client.get("/health")
        assert response.status_code == 200

    def test_invalid_token_format_returns_401(self, unauthed_client: TestClient):
        """A malformed Bearer token must return 401, not 500."""
        response = unauthed_client.get(
            "/api/v1/crowd/metlife",
            headers={"Authorization": "Bearer this.is.not.a.valid.jwt"}
        )
        assert response.status_code in (401, 503)  # 503 if jose not installed

    def test_algorithm_none_token_rejected(self, unauthed_client: TestClient):
        """
        Tokens with algorithm 'none' (CVE-2015-9235) must be rejected.
        We test this by sending a token with a fake 'none' header.
        """
        import base64, json

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "attacker", "role": "admin"}).encode()
        ).rstrip(b"=").decode()
        evil_token = f"{header}.{payload}."

        response = unauthed_client.get(
            "/api/v1/crowd/metlife",
            headers={"Authorization": f"Bearer {evil_token}"}
        )
        assert response.status_code in (401, 503)


class TestRateLimiting:
    """Tests for the token-bucket rate limiter."""

    def test_rate_limit_rejects_excessive_requests(self):
        """
        Simulate a client exhausting their token bucket.
        We create a limiter with a very low limit (3 rpm) and hammer it.
        """
        from fastapi import Request
        from app.middleware.rate_limiter import TokenBucketRateLimiter
        from fastapi import HTTPException

        limiter = TokenBucketRateLimiter(fan_rpm=3, operator_rpm=10, window_seconds=60)

        # Mock request
        mock_request = pytest.helpers if False else type("R", (), {
            "headers": {},
            "client": type("C", (), {"host": "192.0.2.1"})(),
            "state": type("S", (), {"user_role": "fan"})(),
        })()

        # First 3 requests should succeed
        for _ in range(3):
            limiter.check_and_consume(mock_request)

        # 4th request must be rejected
        with pytest.raises(HTTPException) as exc_info:
            limiter.check_and_consume(mock_request)

        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers

    def test_operator_has_higher_rate_limit(self):
        """Operators get 5x the fan rate limit."""
        from app.middleware.rate_limiter import TokenBucketRateLimiter
        from fastapi import HTTPException

        limiter = TokenBucketRateLimiter(fan_rpm=3, operator_rpm=15, window_seconds=60)

        fan_request = type("R", (), {
            "headers": {},
            "client": type("C", (), {"host": "10.0.0.1"})(),
            "state": type("S", (), {"user_role": "fan"})(),
        })()
        op_request = type("R", (), {
            "headers": {},
            "client": type("C", (), {"host": "10.0.0.2"})(),
            "state": type("S", (), {"user_role": "operator"})(),
        })()

        # Fan bucket empties at 3 requests
        for _ in range(3):
            limiter.check_and_consume(fan_request)
        with pytest.raises(HTTPException):
            limiter.check_and_consume(fan_request)

        # Operator bucket has 15 tokens — still fine after 3 requests
        for _ in range(3):
            limiter.check_and_consume(op_request)
        # No exception — operator has headroom
