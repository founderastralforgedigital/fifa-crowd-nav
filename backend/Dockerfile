"""Backend Dockerfile — Multi-stage build for minimal production image."""

# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir build wheel

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]" 2>/dev/null || true

# ── Production stage ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS production

# Security: run as non-root user
RUN groupadd -r appgroup && useradd -r -g appgroup appuser

WORKDIR /app

# Install only production dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir -e "." --no-deps 2>/dev/null || pip install --no-cache-dir fastapi uvicorn[standard] pydantic pydantic-settings python-jose[cryptography] httpx redis[asyncio] structlog passlib[bcrypt] python-multipart

COPY app/ ./app/

# Non-root execution (security)
USER appuser

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
