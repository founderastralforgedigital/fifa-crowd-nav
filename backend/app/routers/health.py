"""
routers/health.py — Health check and metrics endpoints.

GET /health   — Liveness probe (for Docker/Kubernetes)
GET /metrics  — Prometheus-compatible text metrics (for monitoring dashboards)

Health checks MUST respond in < 100ms and must not depend on external
services (databases, GenAI API). A failed external service should not
cause the health check to fail — the pod should stay running to serve
cached data while the dependency recovers.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.config import get_settings

router = APIRouter(tags=["Operations"])

# Track startup time for uptime calculation
_START_TIME = time.monotonic()
_START_DT = datetime.now(timezone.utc).isoformat()

# Simple in-memory counters (in production, use Prometheus client library)
_request_counter: dict[str, int] = {
    "total": 0,
    "navigation": 0,
    "crowd_snapshots": 0,
    "ingestion_batches": 0,
}


@router.get(
    "/health",
    summary="Liveness probe",
    include_in_schema=False,  # Don't expose in API docs (internal endpoint)
)
async def health() -> dict:
    """
    Kubernetes liveness probe endpoint.

    Returns HTTP 200 as long as the application process is alive and
    the event loop is processing requests. Does NOT check external deps.
    """
    settings = get_settings()
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "uptime_seconds": round(time.monotonic() - _START_TIME, 2),
        "started_at": _START_DT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get(
    "/metrics",
    response_class=PlainTextResponse,
    summary="Prometheus metrics",
    include_in_schema=False,
)
async def metrics() -> str:
    """
    Expose application metrics in Prometheus text format.

    In production, replace with the prometheus_fastapi_instrumentator library
    for automatic endpoint-level tracking with histograms and percentiles.
    """
    uptime = time.monotonic() - _START_TIME
    lines = [
        "# HELP fifa_crowd_nav_uptime_seconds Application uptime in seconds",
        "# TYPE fifa_crowd_nav_uptime_seconds gauge",
        f"fifa_crowd_nav_uptime_seconds {uptime:.2f}",
        "",
        "# HELP fifa_crowd_nav_requests_total Total HTTP requests served",
        "# TYPE fifa_crowd_nav_requests_total counter",
        f"fifa_crowd_nav_requests_total{{endpoint=\"all\"}} {_request_counter['total']}",
        f"fifa_crowd_nav_requests_total{{endpoint=\"navigation\"}} {_request_counter['navigation']}",
        f"fifa_crowd_nav_requests_total{{endpoint=\"crowd_snapshot\"}} {_request_counter['crowd_snapshots']}",
        f"fifa_crowd_nav_requests_total{{endpoint=\"ingestion\"}} {_request_counter['ingestion_batches']}",
    ]
    return "\n".join(lines) + "\n"
