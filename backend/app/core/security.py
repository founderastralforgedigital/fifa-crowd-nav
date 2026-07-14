"""
Security utilities: JWT issuance, verification, and password hashing.

Design decisions:
  - RS256 (asymmetric) instead of HS256: The public key can be shared with
    downstream services for independent token verification without exposing
    the signing secret. Critical for a multi-service FIFA 2026 architecture.
  - Separate access and refresh tokens: Short-lived access tokens (60 min)
    minimize exposure window; refresh tokens (7 days) enable seamless UX.
  - Bcrypt for passwords: Adaptive cost factor resists GPU brute-force attacks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# Bcrypt context — auto-upgrades hashes when cost factor increases
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ─── Password Utilities ──────────────────────────────────────────────────────

def hash_password(plain_password: str) -> str:
    """
    Hash a plaintext password using bcrypt.

    Args:
        plain_password: The user-supplied password string.

    Returns:
        A bcrypt hash string safe to store in the database.
    """
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Securely compare a plaintext password against a stored bcrypt hash.

    Uses constant-time comparison internally to prevent timing attacks.

    Args:
        plain_password: The plaintext password to verify.
        hashed_password: The stored bcrypt hash.

    Returns:
        True if the password matches, False otherwise.
    """
    return _pwd_context.verify(plain_password, hashed_password)


# ─── JWT Utilities ───────────────────────────────────────────────────────────

def _build_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    """
    Internal factory for both access and refresh tokens.

    Args:
        subject: The token subject (typically user ID or email).
        token_type: "access" or "refresh" — stored as a claim for validation.
        expires_delta: How long until the token expires.

    Returns:
        A signed JWT string (RS256).
    """
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(
        payload,
        settings.jwt_private_key,
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(subject: str) -> str:
    """
    Create a short-lived JWT access token.

    Args:
        subject: Unique identifier for the token owner (e.g., user UUID).

    Returns:
        Signed JWT access token.
    """
    return _build_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.jwt_access_token_expire_minutes),
    )


def create_refresh_token(subject: str) -> str:
    """
    Create a long-lived JWT refresh token.

    Args:
        subject: Unique identifier for the token owner.

    Returns:
        Signed JWT refresh token.
    """
    return _build_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=settings.jwt_refresh_token_expire_days),
    )


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any]:
    """
    Decode and validate a JWT token.

    Raises:
        JWTError: If the token is invalid, expired, or has the wrong type.
        This exception is caught by the auth dependency and converted to 401.

    Args:
        token: The raw JWT string from the Authorization header.
        expected_type: "access" or "refresh" — prevents refresh tokens from
                       being used as access tokens (confused deputy attack).

    Returns:
        The decoded payload dictionary.
    """
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_public_key,
        algorithms=[settings.jwt_algorithm],
    )

    if payload.get("type") != expected_type:
        logger.warning(
            "jwt_wrong_token_type",
            expected=expected_type,
            received=payload.get("type"),
        )
        raise JWTError("Invalid token type")

    return payload
