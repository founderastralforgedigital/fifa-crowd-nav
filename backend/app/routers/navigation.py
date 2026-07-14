"""
routers/navigation.py — Fan navigation endpoint.

POST /api/v1/navigate — Compute a crowd-optimized, multilingual route.

This is the highest-traffic endpoint during matches. The response is
NOT globally cached because routes are personalized (origin + destination
differ per fan). However, individual GenAI translation steps ARE cached.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_navigation_service
from app.middleware.auth import get_current_user
from app.middleware.rate_limiter import enforce_rate_limit
from app.models.auth import TokenPayload
from app.models.navigation import NavigationRequest, NavigationResponse
from app.services.navigation import NavigationService

router = APIRouter(prefix="/api/v1/navigate", tags=["Navigation"])


@router.post(
    "",
    response_model=NavigationResponse,
    summary="Get crowd-optimized multilingual navigation route",
    description=(
        "Computes the optimal route from origin to destination in a FIFA 2026 stadium, "
        "avoiding congested zones and returning localized, AI-generated step-by-step instructions. "
        "Supports 10 languages including Arabic (RTL) and Chinese."
    ),
    responses={
        200: {"description": "Navigation route computed successfully"},
        400: {"description": "No route found (all paths blocked by CRITICAL density)"},
        401: {"description": "Authentication required"},
        404: {"description": "Stadium or zone not found"},
        429: {"description": "Rate limit exceeded"},
    },
    dependencies=[Depends(enforce_rate_limit)],
)
async def navigate(
    request: NavigationRequest,
    nav_service: NavigationService = Depends(get_navigation_service),
    _: TokenPayload = Depends(get_current_user),
) -> NavigationResponse:
    """
    Compute a crowd-aware navigation route for a fan.

    Request body includes:
    - stadium_id: FIFA 2026 venue identifier
    - origin_zone_id / destination_zone_id: Start and end zones
    - language: Preferred language for instructions (default: EN)
    - accessibility: Standard / Accessible (no stairs) / Medical
    - avoid_zone_ids: Optional zones to exclude from routing

    The route is automatically optimized to avoid HIGH and CRITICAL
    density zones, with step-by-step GenAI-localized instructions.
    """
    try:
        return await nav_service.navigate(request)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": msg},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "navigation_failed", "message": msg},
        )
