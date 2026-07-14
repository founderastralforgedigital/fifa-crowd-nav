"""
routers/stadiums.py — Stadium information endpoints.

GET /api/v1/stadiums        — List all 16 FIFA 2026 host stadiums
GET /api/v1/stadiums/{id}   — Get full stadium details with zone topology

These are read-only, publicly accessible endpoints (no auth required)
to allow fans to browse stadium information before the tournament.

Rate limiting is still enforced to prevent scraping.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_stadium_registry
from app.middleware.rate_limiter import enforce_rate_limit
from app.models.stadium import Stadium, StadiumSummary
from app.services.stadium_registry import StadiumRegistry

router = APIRouter(prefix="/api/v1/stadiums", tags=["Stadiums"])


@router.get(
    "",
    response_model=list[StadiumSummary],
    summary="List all FIFA 2026 host stadiums",
    description=(
        "Returns lightweight summaries for all 16 host cities across USA, Canada, and Mexico. "
        "No authentication required."
    ),
    dependencies=[Depends(enforce_rate_limit)],
)
async def list_stadiums(
    registry: StadiumRegistry = Depends(get_stadium_registry),
) -> list[StadiumSummary]:
    """List all 16 FIFA 2026 host stadiums."""
    return registry.list_stadiums()


@router.get(
    "/{stadium_id}",
    response_model=Stadium,
    summary="Get full stadium details",
    responses={
        404: {"description": "Stadium not found"},
    },
    dependencies=[Depends(enforce_rate_limit)],
)
async def get_stadium(
    stadium_id: str,
    registry: StadiumRegistry = Depends(get_stadium_registry),
) -> Stadium:
    """
    Retrieve full details for a specific stadium including all zone definitions.

    The zone list represents the complete navigable topology and can be used
    to render an interactive stadium map on the client side.
    """
    stadium = registry.get_stadium(stadium_id)
    if stadium is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "stadium_not_found",
                "message": f"Stadium '{stadium_id}' is not a FIFA 2026 host venue",
                "valid_stadiums": [s.stadium_id for s in registry.list_stadiums()],
            },
        )
    return stadium
