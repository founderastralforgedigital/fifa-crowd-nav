"""
middleware/security_headers.py — HTTP security headers middleware.

Security headers are the first line of defense against browser-based attacks.
This middleware adds headers to every response, regardless of endpoint.

Headers implemented:
  - Strict-Transport-Security (HSTS): Forces HTTPS for 1 year
  - Content-Security-Policy (CSP): Restricts resource loading origins
  - X-Content-Type-Options: Prevents MIME-type sniffing
  - X-Frame-Options: Prevents clickjacking
  - Referrer-Policy: Limits referrer information leakage
  - Permissions-Policy: Restricts browser API access (camera, microphone)
  - X-XSS-Protection: Legacy XSS filter for older browsers

References:
  - OWASP Secure Headers Project: https://owasp.org/www-project-secure-headers/
  - MDN Web Docs: https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers
"""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import get_settings


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Starlette middleware that injects security headers on all responses.

    Using BaseHTTPMiddleware integrates cleanly with FastAPI's middleware
    stack and ensures headers are applied even for 4xx/5xx error responses.
    """

    def __init__(self, app, **kwargs) -> None:  # type: ignore
        super().__init__(app, **kwargs)
        settings = get_settings()
        self._is_production = settings.is_production

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore
        response: Response = await call_next(request)

        # Strict-Transport-Security
        # max-age=31536000 = 1 year; includeSubDomains = all subdomains use HTTPS
        # preload = eligible for browser HSTS preload list (submit at hstspreload.org)
        if self._is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # Content-Security-Policy
        # Restricts to same origin + CDN for fonts/icons; blocks inline scripts
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )

        # Prevents browsers from MIME-sniffing a response away from declared content-type
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Prevents the page from being embedded in an <iframe> (clickjacking)
        response.headers["X-Frame-Options"] = "DENY"

        # Limits referrer information to same origin
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Disables browser features not needed by this application
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(self), payment=()"
        )

        # Legacy XSS filter (ignored by modern browsers but harmless)
        response.headers["X-XSS-Protection"] = "1; mode=block"

        return response
