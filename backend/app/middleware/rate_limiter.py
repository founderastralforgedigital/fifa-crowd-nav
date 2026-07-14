"""
middleware/rate_limiter.py — Token-bucket rate limiting middleware.

Rate limiting is critical for this platform because:
  - During match kickoffs and full-time whistles, thousands of fans will
    simultaneously open the navigation app, creating request spikes.
  - The GenAI API has its own rate limits; excessive downstream calls
    would be expensive and degrade the experience for all fans.

Algorithm: Token Bucket
  - Each client (identified by IP + user role) has a "bucket" of tokens.
  - Tokens refill at a constant rate (rpm / 60 = tokens per second).
  - Each request consumes 1 token.
  - If the bucket is empty, the request is rejected with HTTP 429.

Why Token Bucket over Fixed Window?
  - Fixed Window allows burst traffic at window boundaries (e.g., 100 req
    in the last second of minute 1 + 100 req in first second of minute 2
    = 200 req/s burst). Token Bucket smooths this out.
  - Leaky Bucket processes at a fixed rate but doesn't allow short bursts.
    Token Bucket allows small bursts up to the bucket capacity while
    maintaining a long-term average rate — better UX for legitimate fans.

Complexity:
  - get/update bucket state: O(1) (hash map lookup + arithmetic)
  - Memory: O(C) where C = number of distinct clients (bounded by IP space)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.config import get_settings


@dataclass
class _Bucket:
    """
    Token bucket state for a single client.

    tokens:         Current available tokens (float for sub-second precision)
    last_refill_ts: Monotonic timestamp of the last refill operation
    """
    tokens: float
    last_refill_ts: float


class TokenBucketRateLimiter:
    """
    In-memory token-bucket rate limiter.

    Production note: For multi-process/multi-host deployments, this MUST
    be replaced with a Redis-based implementation (e.g., using a Lua script
    for atomic read-modify-write). This in-memory version is correct for
    single-process deployments and serves as the reference implementation.
    """

    def __init__(
        self,
        fan_rpm: int,
        operator_rpm: int,
        window_seconds: int = 60,
    ) -> None:
        self._fan_rate = fan_rpm / window_seconds          # tokens per second
        self._operator_rate = operator_rpm / window_seconds
        self._fan_capacity = float(fan_rpm)                # max burst = 1 minute's worth
        self._operator_capacity = float(operator_rpm)
        # Buckets keyed by client identifier string
        self._buckets: dict[str, _Bucket] = {}

    def _get_client_key(self, request: Request) -> str:
        """
        Derive a stable client identifier from the request.

        Uses X-Forwarded-For if present (behind a reverse proxy) to avoid
        rate-limiting all fans behind the same NAT as a single client.
        """
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For may be a comma-separated list; take the first (original client)
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"

        # Include role in the key so operators get a separate bucket from fans
        role = getattr(request.state, "user_role", "fan")
        return f"{client_ip}:{role}"

    def _get_rate_and_capacity(self, request: Request) -> tuple[float, float]:
        """Return (refill_rate, capacity) based on user role."""
        role = getattr(request.state, "user_role", "fan")
        if role in ("operator", "admin"):
            return self._operator_rate, self._operator_capacity
        return self._fan_rate, self._fan_capacity

    def check_and_consume(self, request: Request) -> None:
        """
        Check if this request is within rate limits and consume a token.

        Raises:
            HTTPException(429): If the client has exhausted their token bucket.
        """
        key = self._get_client_key(request)
        rate, capacity = self._get_rate_and_capacity(request)
        now = time.monotonic()

        if key not in self._buckets:
            # New client: start with a full bucket
            self._buckets[key] = _Bucket(tokens=capacity, last_refill_ts=now)

        bucket = self._buckets[key]

        # Refill: calculate tokens earned since last request
        elapsed = now - bucket.last_refill_ts
        earned_tokens = elapsed * rate
        bucket.tokens = min(capacity, bucket.tokens + earned_tokens)
        bucket.last_refill_ts = now

        if bucket.tokens < 1.0:
            # Calculate how long the client must wait for 1 token
            retry_after = int((1.0 - bucket.tokens) / rate) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": (
                        "Too many requests. During peak match periods, please retry after "
                        f"{retry_after} seconds."
                    ),
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Consume one token
        bucket.tokens -= 1.0


# Module-level singleton — instantiated once at startup
_settings = get_settings()
rate_limiter = TokenBucketRateLimiter(
    fan_rpm=_settings.rate_limit_fan_rpm,
    operator_rpm=_settings.rate_limit_operator_rpm,
    window_seconds=_settings.rate_limit_window_seconds,
)


async def enforce_rate_limit(request: Request) -> None:
    """
    FastAPI dependency that enforces the rate limit for incoming requests.

    Usage in a router:
        @router.get("/...", dependencies=[Depends(enforce_rate_limit)])
    """
    rate_limiter.check_and_consume(request)
