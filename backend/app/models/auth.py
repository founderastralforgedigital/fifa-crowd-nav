"""
models/auth.py — Pydantic models for JWT authentication.

We use RS256 (asymmetric) JWT rather than HS256 to allow multiple downstream
services to verify tokens using only the public key, without ever exposing
the signing secret. This is critical at FIFA 2026 scale where dozens of
microservices may need to validate fan/operator identity.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, EmailStr


class UserRole(str, Enum):
    """
    Access control roles.

    FAN      — read-only navigation and crowd data
    OPERATOR — read + write; can ingest sensor data
    ADMIN    — full access including metrics and config
    """
    FAN = "fan"
    OPERATOR = "operator"
    ADMIN = "admin"


class TokenPayload(BaseModel):
    """
    Claims embedded in the JWT access token.

    Mirrors the standard JWT registered claims (RFC 7519) plus
    application-specific claims (role, stadium_ids).
    """
    sub: str = Field(..., description="Subject: user ID")
    role: UserRole
    exp: datetime
    iat: datetime
    jti: str = Field(..., description="JWT ID: unique token identifier for revocation")
    # Operator/admin tokens may be scoped to specific stadiums
    stadium_ids: list[str] = Field(
        default_factory=list,
        description="Empty list means access to all stadiums"
    )


class TokenResponse(BaseModel):
    """Response body for successful authentication."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Seconds until token expiry")


class LoginRequest(BaseModel):
    """Credential payload for obtaining an access token."""
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)

    class Config:
        extra = "forbid"
