"""
main.py — FastAPI application entrypoint.

This module creates and configures the FastAPI application instance.
It wires together:
  - Middleware stack (security headers, CORS)
  - Route handlers
  - Startup/shutdown lifecycle hooks
  - Global exception handlers

Application startup is O(1) — all expensive initialization (stadium graph,
cache connections) is deferred to the first request via dependency injection.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import crowd, health, navigation, stadiums

# Configure structured logging at module load time
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger(__name__)
settings = get_settings()


def create_app() -> FastAPI:
    """
    Application factory.

    Using a factory function (instead of a module-level `app = FastAPI()`)
    enables easy test isolation: each test can call `create_app()` to get
    a fresh instance with independent state and dependency overrides.
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "GenAI-Enabled Predictive Crowd Flow & Multilingual Navigation System "
            "for FIFA World Cup 2026. Serving 48 teams, 16 host cities, 3 countries."
        ),
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        license_info={"name": "Proprietary — FIFA 2026 Platform", "url": "https://fifa.com"},
    )

    # ── Middleware (applied in reverse order — last added = first executed) ───
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],  # Only the methods we actually use
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(stadiums.router)
    app.include_router(crowd.router)
    app.include_router(navigation.router)

    # ── Global Exception Handlers ─────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch-all for unhandled exceptions.

        Returns a generic 500 response to the client (never expose stack traces
        in production) while logging the full exception server-side.
        """
        logger.error(
            "unhandled_exception",
            path=str(request.url),
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred. Our team has been notified.",
            },
        )

    # ── Lifecycle Hooks ───────────────────────────────────────────────────────
    @app.on_event("startup")
    async def startup() -> None:
        logger.info(
            "application.startup",
            name=settings.app_name,
            version=settings.app_version,
            environment=settings.app_env,
        )

    @app.on_event("shutdown")
    async def shutdown() -> None:
        logger.info("application.shutdown")

    return app


# Module-level app instance (used by uvicorn entrypoint)
app = create_app()
