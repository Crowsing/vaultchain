"""Pydantic Settings — single source of all environment configuration.

Every env var the project will EVER need is listed here. Phase briefs
that consume new vars MUST add them here first; CI verifies that production
deploys can supply them.

Sectioned by phase that introduces the var. Optional fields default to None
so Phase 1 boots without Phase 4 secrets.
"""

from __future__ import annotations

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------- core / phase 1 -------------
    environment: str = Field(default="dev", description="dev | test | staging | production")
    secret_key: SecretStr = Field(..., min_length=32)
    database_url: str = Field(..., description="postgresql+asyncpg URL")
    redis_url: str = Field(..., description="redis:// or rediss:// URL")
    sentry_dsn_backend: str | None = None
    log_level: str = "INFO"

    # ------------- email / phase 1 -------------
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    email_from: str = "noreply@vaultchain.example"
    resend_api_key: SecretStr | None = None

    # ------------- KMS / phase 2 -------------
    aws_region: str = "us-east-1"
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None
    kms_key_id: str | None = None

    # ------------- chains / phase 2-3 -------------
    eth_rpc_url: str = "http://localhost:8545"
    eth_chain_id: int = 11155111  # sepolia
    tron_node_url: str = "https://api.shasta.trongrid.io"
    solana_rpc_url: str = "https://api.devnet.solana.com"

    # ------------- KYC / phase 2 -------------
    sumsub_app_token: SecretStr | None = None
    sumsub_secret_key: SecretStr | None = None
    sumsub_webhook_secret: SecretStr | None = None

    # ------------- pricing / phase 3 -------------
    coingecko_api_key: SecretStr | None = None

    # ------------- AI / phase 4 -------------
    anthropic_api_key: SecretStr | None = None
    google_ai_studio_api_key: SecretStr | None = None
    ai_model_planner: str = "claude-opus-4-7"
    ai_model_chat: str = "claude-sonnet-4-6"
    ai_embedding_model: str = "embedding-001"

    # ------------- notifications / phase 1 -------------
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    # ------------- CORS / phase 1 -------------
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:5174"]


_settings: Settings | None = None


def get_settings() -> Settings:
    """Lazy singleton accessor. Use this everywhere — never instantiate Settings()."""
    global _settings  # noqa: PLW0603 — module-level cache is the intended pattern
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """Test-only: drop cached settings so env changes take effect."""
    global _settings  # noqa: PLW0603 — module-level cache is the intended pattern
    _settings = None
