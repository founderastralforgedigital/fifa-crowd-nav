"""
Authentication API endpoints.

Provides login and token refresh. User registration is intentionally
excluded — FIFA fan accounts are pre-provisioned via ticketing integration.

Rate limiting: Strict 5/min to prevent brute-force attacks on fan accounts.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from app.core.rate_limiter import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_password,
    decode_token,
)
from app.config import get_settings
from jose import JWTError

settings = get_settings()
router = APIRouter()


class LoginRequest(BaseModel):
    """Fan login credentials."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    """JWT token pair response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


class RefreshRequest(BaseModel):
    """Refresh token request."""

    refresh_token: str


# ── Mock user store (replace with DB lookup in production) ──────────────────
# In production: async lookup from PostgreSQL via UserRepository
_MOCK_USERS: dict[str, dict] = {
    "fan@example.com": {
        "id": "usr_001",
        # bcrypt hash of "SecurePass123!" — generated with hash_password()
        "hashed_password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        "role": "fan",
    },
    "operator@fifa2026.com": {
        "id": "usr_002",
        "hashed_password": "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW",
        "role": "operator",
    },
}


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate fan and receive JWT tokens",
)
@limiter.limit(settings.rate_limit_auth)
async def login(request: Request, credentials: LoginRequest) -> TokenResponse:
    """
    Authenticate a fan with email/password and issue JWT tokens.

    Security notes:
      - verify_password uses constant-time bcrypt comparison (no timing attacks).
      - The same "Invalid credentials" error is returned whether the user
        doesn't exist OR the password is wrong (prevents user enumeration).
      - Rate limited to 5/min to prevent brute force.
    """
    user = _MOCK_USERS.get(credentials.email)

    # Deliberate: unified error prevents email enumeration
    if user is None or not verify_password(credentials.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(subject=user["id"])
    refresh_token = create_refresh_token(subject=user["id"])

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in_seconds=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token using refresh token",
)
@limiter.limit(settings.rate_limit_auth)
async def refresh_token(request: Request, payload: RefreshRequest) -> TokenResponse:
    """
    Issue a new access token using a valid refresh token.

    The refresh token type check in decode_token() prevents access tokens
    from being used here (confused deputy attack prevention).
    """
    try:
        token_data = decode_token(payload.refresh_token, expected_type="refresh")
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    new_access_token = create_access_token(subject=token_data["sub"])
    new_refresh_token = create_refresh_token(subject=token_data["sub"])

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in_seconds=settings.jwt_access_token_expire_minutes * 60,
    )
