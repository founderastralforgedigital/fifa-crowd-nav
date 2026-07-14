"""
tests/conftest.py — Pytest fixtures shared across all test modules.

Design principles:
  1. Every test is isolated — fixtures create fresh instances.
  2. All external dependencies (GenAI API, Redis) are mocked by default.
  3. The FastAPI test client uses the application factory so dependency
     overrides work cleanly.
  4. Fixtures are typed for IDE support and early error detection.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.main import create_app
from app.models.auth import TokenPayload, UserRole
from app.models.stadium import Coordinates, Country, Stadium, StadiumZone, ZoneType
from app.services.cache import InMemoryCacheService
from app.services.crowd_flow import CrowdFlowService
from app.services.genai_translation import GenAITranslationService
from app.services.navigation import NavigationService
from app.services.stadium_registry import StadiumRegistry
from app.utils.graph import WeightedGraph


# ── Shared test constants ─────────────────────────────────────────────────────

TEST_STADIUM_ID = "test_stadium"
TEST_ORIGIN = "GATE_N"
TEST_DESTINATION = "EXIT_E"


# ── Fixtures: Infrastructure ──────────────────────────────────────────────────

@pytest.fixture
def in_memory_cache() -> InMemoryCacheService:
    """Fresh in-memory cache for each test — no shared state between tests."""
    return InMemoryCacheService()


@pytest.fixture
def simple_graph() -> WeightedGraph:
    """
    A minimal 4-node graph for testing routing logic.

    Topology:
        A --10-- B --10-- D
        |               /
        20             15
        |             /
        C -----------
    """
    g = WeightedGraph()
    g.add_edge("A", "B", base_weight=10.0)
    g.add_edge("B", "D", base_weight=10.0)
    g.add_edge("A", "C", base_weight=20.0)
    g.add_edge("C", "D", base_weight=15.0)
    g.add_edge("B", "A", base_weight=10.0)  # bidirectional
    return g


@pytest.fixture
def registry() -> StadiumRegistry:
    """Real StadiumRegistry with all 16 FIFA 2026 host stadiums."""
    return StadiumRegistry()


@pytest.fixture
def crowd_service(registry: StadiumRegistry) -> CrowdFlowService:
    """CrowdFlowService backed by the real registry, fresh state."""
    return CrowdFlowService(registry=registry)


@pytest.fixture
def mock_translation_service() -> MagicMock:
    """
    Mock GenAITranslationService that returns predictable English strings
    without calling the real GenAI API.
    """
    mock = MagicMock(spec=GenAITranslationService)
    mock.generate_navigation_instruction = AsyncMock(
        return_value="Walk straight toward the exit."
    )
    mock.generate_crowd_warning = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def navigation_service(
    registry: StadiumRegistry,
    crowd_service: CrowdFlowService,
    mock_translation_service: MagicMock,
    in_memory_cache: InMemoryCacheService,
) -> NavigationService:
    """NavigationService with all real components except GenAI (mocked)."""
    return NavigationService(
        registry=registry,
        crowd_service=crowd_service,
        translation_service=mock_translation_service,
        cache=in_memory_cache,
    )


# ── Fixtures: Authentication ──────────────────────────────────────────────────

@pytest.fixture
def fan_token_payload() -> TokenPayload:
    """Mock fan JWT payload for testing auth-protected endpoints."""
    return TokenPayload(
        sub="fan-user-001",
        role=UserRole.FAN,
        exp=datetime(2099, 1, 1, tzinfo=timezone.utc),
        iat=datetime(2026, 7, 14, tzinfo=timezone.utc),
        jti="test-jti-fan-001",
        stadium_ids=[],
    )


@pytest.fixture
def operator_token_payload() -> TokenPayload:
    """Mock operator JWT payload."""
    return TokenPayload(
        sub="operator-001",
        role=UserRole.OPERATOR,
        exp=datetime(2099, 1, 1, tzinfo=timezone.utc),
        iat=datetime(2026, 7, 14, tzinfo=timezone.utc),
        jti="test-jti-op-001",
        stadium_ids=[],
    )


# ── Fixtures: FastAPI Test Client ─────────────────────────────────────────────

@pytest.fixture
def app_client(
    fan_token_payload: TokenPayload,
    crowd_service: CrowdFlowService,
    navigation_service: NavigationService,
    registry: StadiumRegistry,
):
    """
    FastAPI TestClient with all dependencies overridden.

    Auth is bypassed by overriding get_current_user to return the fan payload.
    This allows testing endpoint logic without valid JWT infrastructure.
    """
    from app.dependencies import (
        get_crowd_service,
        get_navigation_service,
        get_stadium_registry,
    )
    from app.middleware.auth import get_current_user
    from app.middleware.rate_limiter import enforce_rate_limit

    application = create_app()

    # Override dependencies
    application.dependency_overrides[get_current_user] = lambda: fan_token_payload
    application.dependency_overrides[enforce_rate_limit] = lambda: None
    application.dependency_overrides[get_stadium_registry] = lambda: registry
    application.dependency_overrides[get_crowd_service] = lambda: crowd_service
    application.dependency_overrides[get_navigation_service] = lambda: navigation_service

    with TestClient(application) as client:
        yield client
