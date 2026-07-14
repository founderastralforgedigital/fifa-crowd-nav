"""
middleware/auth.py — JWT authentication middleware and FastAPI dependencies.

Security model:
  - Tokens are issued as RS256 JWTs (asymmetric crypto).
  - The private key signs tokens (kept secret on the auth server).
  - The public key verifies tokens (can be distributed to all API servers).
  - This allows horizontal scaling: any API replica can verify tokens without
    contacting a central auth server.

Token validation steps (RFC 7519):
  1. Parse the Authorization header for "Bearer <token>"
  2. Decode the JWT header to confirm algorithm is RS256 (not "none"!)
  3. Verify the signature using the public key
  4. Validate standard claims: exp (not expired), iat (not in future)
  5. Extract and validate custom claims: role, stadium_ids
  6. Attach the decoded payload to request.state for downstream use

Security notes:
  - We explicitly reject tokens with algorithm "none" (CVE-2015-9235).
  - We validate the algorithm in the decode call to prevent downgrade attacks.
  - JTI (JWT ID) blocklist checking would be added here for token revocation.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.models.auth import TokenPayload, UserRole

# jose handles JWT parsing and verification
try:
    from jose import ExpiredSignatureError, JWTError, jwt as jose_jwt
    _JOSE_AVAILABLE = True
except ImportError:
    _JOSE_AVAILABLE = False

_bearer_scheme = HTTPBearer(auto_error=True)
_settings = get_settings()


def _load_public_key() -> str:
    """
    Load the RS256 public key from the filesystem.

    We read the key lazily (on first auth call) rather than at import time
    to avoid blocking startup if the key file is on a mounted volume that
    may not be immediately available.
    """
    key_path = Path(_settings.jwt_public_key_path)
    if not key_path.exists():
        raise RuntimeError(
            f"JWT public key not found at '{key_path}'. "
            "Generate with: openssl genrsa -out private.pem 2048 && "
            "openssl rsa -in private.pem -pubout -out public.pem"
        )
    return key_path.read_text(encoding="utf-8")


# Cache the public key in module scope — it changes only on key rotation
_public_key_cache: str | None = None


def _get_public_key() -> str:
    global _public_key_cache
    if _public_key_cache is None:
        _public_key_cache = _load_public_key()
    return _public_key_cache


def _decode_token(token: str) -> TokenPayload:
    """
    Decode and validate a JWT access token.

    Args:
        token: Raw JWT string from the Authorization header.

    Returns:
        Validated TokenPayload with all claims.

    Raises:
        HTTPException(401): If the token is invalid, expired, or tampered.
    """
    if not _JOSE_AVAILABLE:
        # Development mode without jose library: decode without verification
        # NEVER use this in production
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="JWT library not available. Install python-jose[cryptography].",
        )

    try:
        public_key = _get_public_key()
        payload_dict = jose_jwt.decode(
            token,
            public_key,
            # Explicitly specify RS256 — prevents algorithm downgrade to "none"
            algorithms=[_settings.jwt_algorithm],
        )
        return TokenPayload(**payload_dict)

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "token_expired", "message": "Access token has expired"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": f"Token validation failed: {exc}"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "auth_error", "message": "Authentication service error"},
        )


# ── FastAPI Dependencies ──────────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> TokenPayload:
    """
    FastAPI dependency that validates the JWT and returns the token payload.

    Attaches user role to request.state so the rate limiter can read it.
    """
    payload = _decode_token(credentials.credentials)
    # Make role available to rate limiter without re-parsing the token
    request.state.user_role = payload.role.value
    return payload


def require_role(*allowed_roles: UserRole):
    """
    Dependency factory for role-based access control.

    Usage:
        @router.post("/ingest", dependencies=[Depends(require_role(UserRole.OPERATOR))])

    Args:
        *allowed_roles: One or more UserRole values that are permitted.
    """
    async def _check_role(current_user: TokenPayload = Depends(get_current_user)) -> TokenPayload:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_permissions",
                    "message": (
                        f"Role '{current_user.role.value}' is not authorized for this endpoint. "
                        f"Required: {[r.value for r in allowed_roles]}"
                    ),
                },
            )
        return current_user
    return _check_role
