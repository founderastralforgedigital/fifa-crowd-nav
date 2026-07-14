"""
routers/crowd.py — Crowd density data endpoints.

GET  /api/v1/crowd/{stadium_id}  — Current crowd snapshot (fans, auth required)
POST /api/v1/crowd/ingest        — Ingest sensor data (operators only)

Security: Ingestion requires OPERATOR or ADMIN role to prevent fans from
injecting false crowd data that could create artificial "clear path" reports.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_crowd_service
from app.middleware.auth import get_current_user, require_role
from app.middleware.rate_limiter import enforce_rate_limit
from app.models.auth import TokenPayload, UserRole
from app.models.crowd import CrowdDataIngestionRequest, StadiumCrowdSnapshot
from app.services.crowd_flow import CrowdFlowService

router = APIRouter(prefix="/api/v1/crowd", tags=["Crowd Flow"])


@router.get(
    "/{stadium_id}",
    response_model=StadiumCrowdSnapshot,
    summary="Get real-time crowd density snapshot",
    description=(
        "Returns per-zone crowd density, bottleneck predictions, and overall stadium state. "
        "Poll every 30 seconds for real-time updates."
    ),
    responses={
        404: {"description": "Stadium not found"},
        401: {"description": "Authentication required"},
    },
    dependencies=[Depends(enforce_rate_limit)],
)
async def get_crowd_snapshot(
    stadium_id: str,
    crowd_service: CrowdFlowService = Depends(get_crowd_service),
    _: TokenPayload = Depends(get_current_user),  # Auth required; payload unused
) -> StadiumCrowdSnapshot:
    """
    Retrieve the current crowd density state for all zones in a stadium.

    The response includes:
    - Per-zone occupancy counts and density levels
    - 15-minute density predictions (linear extrapolation)
    - List of active bottleneck zone IDs (density HIGH or CRITICAL)
    """
    try:
        return await crowd_service.get_snapshot(stadium_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "stadium_not_found", "message": str(exc)},
        )


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest crowd sensor/ticketing data",
    description=(
        "Accepts batched sensor readings and updates the real-time crowd model. "
        "Restricted to OPERATOR and ADMIN roles."
    ),
    responses={
        202: {"description": "Data accepted and processing"},
        403: {"description": "Insufficient role permissions"},
        422: {"description": "Validation error in sensor readings"},
    },
    dependencies=[Depends(enforce_rate_limit)],
)
async def ingest_crowd_data(
    request: CrowdDataIngestionRequest,
    crowd_service: CrowdFlowService = Depends(get_crowd_service),
    current_user: TokenPayload = Depends(require_role(UserRole.OPERATOR, UserRole.ADMIN)),
) -> dict:
    """
    Ingest a batch of sensor readings to update the crowd model.

    Accepts up to 500 readings per request.
    Timestamps within a batch must span no more than 5 minutes.
    """
    try:
        zones_updated = await crowd_service.ingest(request)
        return {
            "status": "accepted",
            "batch_id": request.batch_id,
            "stadium_id": request.stadium_id,
            "zones_updated": zones_updated,
            "ingested_by": current_user.sub,
        }
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "ingestion_failed", "message": str(exc)},
        )
