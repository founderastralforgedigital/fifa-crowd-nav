"""
API v1 router — aggregates all endpoint routers into a single prefix.
"""

from fastapi import APIRouter

from app.api.v1.crowd import router as crowd_router
from app.api.v1.navigation import router as navigation_router
from app.api.v1.auth import router as auth_router

api_v1_router = APIRouter()

api_v1_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(crowd_router, prefix="/crowd", tags=["Crowd Analytics"])
api_v1_router.include_router(navigation_router, prefix="/navigation", tags=["Navigation"])
