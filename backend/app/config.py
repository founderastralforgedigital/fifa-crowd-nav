"""
Application configuration module.

Uses Pydantic Settings v2 to load and validate all configuration from
environment variables. This is the SINGLE SOURCE OF TRUTH for all
app-level settings — no magic strings elsewhere in the codebase.

Why Pydantic Settings?
  - Automatic env var loading and type coercion.
  - Validation at startup → fail-fast on misconfiguration.
  - Supports .env files for local development without changing code.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central settings class. All fields are loaded from environment variables.
    Required fields (no default) will raise a ValueError at startup if missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Prevent extra fields from silently being ignored
        extra="forbid",
    )

    # ─── Application ────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = False
    app_secret_key: str = Field(min_length=32)

    # ─── JWT ────────────────────────────────────────────────────────────
    jwt_private_key_b64: str
    jwt_public_key_b64: str
    jwt_algorithm: str = "RS256"
    jwt_access_token_expire_minutes: int = 60
    jwt_refresh_token_expire_days: int = 7

    @computed_field  # type: ignore[prop-decorator]
    @property
    def jwt_private_key(self) -> str:
        """Decode base64-encoded RSA private key for JWT signing."""
        return base64.b64decode(self.jwt_private_key_b64).decode("utf-8")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def jwt_public_key(self) -> str:
        """Decode base64-encoded RSA public key for JWT verification."""
        return base64.b64decode(self.jwt_public_key_b64).decode("utf-8")

    # ─── Database ───────────────────────────────────────────────────────
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    database_pool_min: int = 5
    database_pool_max: int = 20

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """
        Constructs the async PostgreSQL DSN.
        asyncpg requires 'postgresql+asyncpg://' scheme.
        """
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ─── Redis ──────────────────────────────────────────────────────────
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str
    redis_db: int = 0
    redis_crowd_cache_ttl: int = 30
    redis_route_cache_ttl: int = 3600
    redis_genai_cache_ttl: int = 300

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        """Constructs the Redis connection URL with auth credentials."""
        return (
            f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}"
            f"/{self.redis_db}"
        )

    # ─── Google Gemini ───────────────────────────────────────────────────
    gemini_api_key: str
    gemini_model: str = "gemini-1.5-pro"
    gemini_max_output_tokens: int = 512
    gemini_temperature: float = Field(default=0.3, ge=0.0, le=1.0)

    # ─── Rate Limiting ───────────────────────────────────────────────────
    rate_limit_default: str = "100/minute"
    rate_limit_genai: str = "10/minute"
    rate_limit_auth: str = "5/minute"

    # ─── CORS ────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:5173"]

    @model_validator(mode="before")
    @classmethod
    def parse_cors_origins(cls, values: dict) -> dict:
        """Allow CORS_ORIGINS to be a comma-separated string in .env."""
        if "cors_origins" in values and isinstance(values["cors_origins"], str):
            values["cors_origins"] = [
                origin.strip() for origin in values["cors_origins"].split(",")
            ]
        return values

    # ─── Logging ─────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"

    # ─── Feature Flags ───────────────────────────────────────────────────
    enable_genai: bool = True
    enable_websockets: bool = True

    @property
    def is_production(self) -> bool:
        """Convenience property to check if running in production mode."""
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached singleton of the Settings instance.
    The @lru_cache ensures env vars are read only ONCE per process,
    making repeated calls free (O(1) dict lookup).
    """
    return Settings()
