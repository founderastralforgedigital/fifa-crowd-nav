"""
Custom ASGI middleware for security hardening and observability.

SecurityHeadersMiddleware:
  Adds HTTP security headers to every response. These are defense-in-depth
  measures recommended by OWASP for production web applications.

RequestLoggingMiddleware:
  Structured JSON logging for every request/response cycle. Includes a
  unique X-Request-ID header for distributed tracing across microservices.
"""

from __future__ import annotations

import time
import uuid
from typing import Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Injects OWASP-recommended HTTP security headers into every response.

    Headers applied:
      - X-Content-Type-Options: Prevents MIME-sniffing (XSS vector).
      - X-Frame-Options: Clickjacking protection (DENY by default).
      - X-XSS-Protection: Legacy XSS filter for older browsers.
      - Strict-Transport-Security: Force HTTPS for 1 year (production only).
      - Content-Security-Policy: Restricts script/style sources.
      - Referrer-Policy: Limits information leakage in Referer header.
      - Permissions-Policy: Disables sensitive browser APIs.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response: Response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self' wss:; "
            "frame-ancestors 'none';"
        )

        # Only apply HSTS in production (would break local HTTPS dev setups)
        from app.config import get_settings
        if get_settings().is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Structured per-request logging with timing and correlation IDs.

    Each request gets a UUID (X-Request-ID) for distributed tracing.
    The same ID is echoed in the response header so clients can correlate
    support tickets to specific log entries.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())
        start_time = time.monotonic()

        # Bind request ID to all log entries in this request context
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            logger.info(
                "request_received",
                method=request.method,
                path=request.url.path,
                client_ip=request.client.host if request.client else "unknown",
            )

            response: Response = await call_next(request)
            duration_ms = round((time.monotonic() - start_time) * 1000, 2)

            logger.info(
                "request_completed",
                status_code=response.status_code,
                duration_ms=duration_ms,
            )

            response.headers["X-Request-ID"] = request_id
            return response
