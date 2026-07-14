"""
Rate limiting configuration using SlowAPI (Starlette-native wrapper over limits).

FIFA 2026 context: During high-stakes matches (quarter-finals, semis, final),
API traffic can spike to 50,000+ requests/second across all stadiums. Rate
limiting is a critical DDoS defense and fair-use enforcement layer.

Implementation details:
  - Uses Redis as the shared backend: limits are enforced across ALL worker
    processes, not just per-process (unlike in-memory backends).
  - Sliding window algorithm: fairer than fixed window — prevents burst abuse
    at window boundaries (e.g., 99 requests at 11:59 + 99 at 12:00).
  - Key function: limits by real IP, correctly extracting from X-Forwarded-For
    when behind a load balancer.
"""

from __future__ import annotations

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()


def _get_real_ip(request: Request) -> str:
    """
    Extract the real client IP, accounting for reverse proxies.

    X-Forwarded-For can contain a comma-separated list of IPs (proxy chain).
    We take the FIRST entry — the original client IP — not the proxy IP.
    This is critical in a multi-CDN FIFA deployment where many requests
    share a single proxy IP (which would unfairly block all fans behind it).

    Args:
        request: The incoming Starlette request.

    Returns:
        Real client IP address string.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take leftmost (most-specific / original client) IP
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request)


# Global limiter instance — shared across all routers
# The storage_uri connects to Redis for distributed rate state
limiter = Limiter(
    key_func=_get_real_ip,
    storage_uri=settings.redis_url,
    strategy="sliding-window",
)
