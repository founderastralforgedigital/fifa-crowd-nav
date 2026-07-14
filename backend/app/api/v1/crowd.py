"""
Crowd analytics API endpoints.

Exposes stadium crowd density data and bottleneck predictions.
Also provides a WebSocket endpoint for real-time push to fan devices.

Rate limiting: Standard 100/min for REST endpoints.
WebSocket: No rate limit (connection-based, managed by connection pool).

All endpoints require JWT authentication — unauthenticated access to crowd
data could be exploited for venue-targeting by bad actors during FIFA events.
"""

from __future__ import annotations

import json
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.rate_limiter import limiter
from app.dependencies import Cache, CurrentUser
from app.domain.models.crowd import StadiumCrowdSnapshot
from app.domain.services.crowd_analytics import CrowdAnalyticsService
from app.infrastructure.cache import CacheClient

# Import the mock stadium graph seeder for demo data
from app.domain.repositories.stadium_repository import get_or_create_stadium_graph

logger = structlog.get_logger(__name__)
settings = get_settings()
router = APIRouter()


# ─── Request / Response Schemas ──────────────────────────────────────────────

class CrowdIngestRequest(BaseModel):
    """
    Inbound payload for ingesting real-time crowd sensor data.
    In production this would come from automated sensor pipelines,
    not a human-facing API — but the endpoint exists for integration testing
    and manual data injection during stadium ops.
    """

    stadium_id: str = Field(
        ...,
        pattern=r"^[A-Z_]{3,20}$",
        examples=["METLIFE", "ATT_STADIUM"],
    )
    match_id: UUID
    zone_counts: dict[str, int] = Field(
        ...,
        description="Maps zone_id → current fan count",
        min_length=1,
        max_length=1000,  # Cap to prevent abuse: no stadium has > 1000 zones
    )
    match_event: str | None = Field(
        default=None,
        pattern=r"^[A-Z_]{2,30}$",
        description="Optional current match event (e.g., 'HALF_TIME', 'GOAL')",
    )


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post(
    "/ingest",
    response_model=StadiumCrowdSnapshot,
    status_code=status.HTTP_200_OK,
    summary="Ingest real-time crowd sensor data",
    description=(
        "Receives raw sensor zone counts, computes congestion levels, "
        "predicts bottlenecks, and broadcasts to connected WebSocket clients. "
        "Requires operator-level JWT."
    ),
)
@limiter.limit(settings.rate_limit_default)
async def ingest_crowd_data(
    request: Request,  # Required by SlowAPI for IP extraction
    payload: CrowdIngestRequest,
    current_user: CurrentUser,
    cache: Cache,
) -> StadiumCrowdSnapshot:
    """Ingest sensor data and compute a live crowd snapshot."""

    graph = get_or_create_stadium_graph(payload.stadium_id)

    # Zone capacities come from the graph node definitions
    zone_capacities = {
        node_id: node.capacity
        for node_id, node in graph.nodes.items()
    }

    analytics = CrowdAnalyticsService(graph=graph)
    snapshot = analytics.compute_snapshot(
        stadium_id=payload.stadium_id,
        match_id=payload.match_id,
        raw_zone_counts=payload.zone_counts,
        zone_capacities=zone_capacities,
        match_event=payload.match_event,
    )

    # Cache snapshot for WebSocket consumers and subsequent REST reads
    cache_key = f"snapshot:{payload.stadium_id}"
    await cache.set(
        key=cache_key,
        value=snapshot.model_dump_json(),
        ttl=settings.redis_crowd_cache_ttl,
    )

    # Broadcast to all connected WebSocket subscribers for this stadium
    await cache.publish(
        channel=f"crowd:{payload.stadium_id}",
        message=snapshot.model_dump_json(),
    )

    logger.info(
        "crowd_data_ingested",
        stadium_id=payload.stadium_id,
        match_id=str(payload.match_id),
        ingested_by=current_user.get("sub"),
    )

    return snapshot


@router.get(
    "/{stadium_id}/snapshot",
    response_model=StadiumCrowdSnapshot,
    summary="Get current crowd snapshot for a stadium",
)
@limiter.limit(settings.rate_limit_default)
async def get_crowd_snapshot(
    request: Request,
    stadium_id: str,
    current_user: CurrentUser,
    cache: Cache,
) -> StadiumCrowdSnapshot:
    """
    Retrieve the most recent cached crowd snapshot for a stadium.

    Returns the last snapshot computed by the ingest pipeline (cached in Redis).
    Cache TTL is 30 seconds — data is guaranteed to be at most 30s stale.

    Raises:
        404: If no snapshot exists yet for this stadium (pre-match).
    """
    # Validate stadium_id before using as cache key (prevent injection)
    if not stadium_id.replace("_", "").isalpha() or len(stadium_id) > 20:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid stadium_id format",
        )

    cache_key = f"snapshot:{stadium_id}"
    raw = await cache.get(cache_key)

    if raw is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No crowd data available for stadium '{stadium_id}'. "
                   "Match may not have started yet.",
        )

    return StadiumCrowdSnapshot.model_validate_json(raw)


@router.websocket("/{stadium_id}/live")
async def crowd_live_stream(
    websocket: WebSocket,
    stadium_id: str,
) -> None:
    """
    WebSocket endpoint for real-time crowd density streaming.

    Fans connect once; the server pushes crowd snapshots whenever new
    sensor data is ingested (via Redis pub/sub). No polling required.

    Protocol:
      - Client connects: immediately receives the latest cached snapshot.
      - Server pushes: new snapshot JSON on every crowd data ingest.
      - Client disconnect: connection closes silently (no error).

    FIFA 2026 context: Peak concurrent WebSocket connections during the World
    Cup Final are estimated at ~60,000 (one per fan in the stadium).
    """
    if not settings.enable_websockets:
        await websocket.close(code=1001, reason="WebSocket disabled")
        return

    await websocket.accept()

    try:
        from app.infrastructure.cache import get_cache_client
        import redis.asyncio as aioredis

        redis_client = await get_cache_client()
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"crowd:{stadium_id}")

        logger.info("websocket_connected", stadium_id=stadium_id)

        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])

    except WebSocketDisconnect:
        logger.info("websocket_disconnected", stadium_id=stadium_id)
    except Exception as exc:
        logger.error("websocket_error", stadium_id=stadium_id, error=str(exc))
        await websocket.close(code=1011)
    finally:
        try:
            await pubsub.unsubscribe(f"crowd:{stadium_id}")
        except Exception:
            pass
