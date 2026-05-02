"""Pydantic Settings — single source of all environment configuration.

Every env var the project will EVER need is listed here. Phase briefs
that consume new vars MUST add them here first; CI verifies that production
deploys can supply them.

Sectioned by phase that introduces the var. Optional fields default to None
so Phase 1 boots without Phase 4 secrets.
"""

from __future__ import annotations

import os
from typing import Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine.url import make_url

# `secrets_dir` lets pydantic-settings transparently read SecretStr fields
# from `/run/secrets/<field_name>` files when no env var of the same name is
# set. Matches docker-compose-prod.yml's `secrets:` mounts — without it the
# api/worker containers crash on boot because SECRET_KEY, SUMSUB_*,
# ANTHROPIC_API_KEY, etc. are only passed as `*_FILE=<path>` env vars that
# pydantic doesn't natively understand.
#
# Resolve to None in dev/CI/test where /run/secrets isn't mounted, otherwise
# pydantic-settings emits a UserWarning at every Settings() instantiation.
_SECRETS_DIR: str | None = "/run/secrets" if os.path.isdir("/run/secrets") else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        secrets_dir=_SECRETS_DIR,
    )

    # ------------- core / phase 1 -------------
    environment: str = Field(default="dev", description="dev | test | staging | production")
    secret_key: SecretStr = Field(..., min_length=32)
    master_key_path: str | None = None
    database_url: str = Field(..., description="postgresql+asyncpg URL")
    #: Read from `/run/secrets/postgres_password` when DATABASE_URL is supplied
    #: without an embedded password (the prod compose pattern). The
    #: ``_inject_db_password`` validator splices it into ``database_url``.
    postgres_password: SecretStr | None = None
    redis_url: str = Field(..., description="redis:// or rediss:// URL")
    sentry_dsn_backend: str | None = None
    log_level: str = "INFO"

    # ------------- email / phase 1 -------------
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    email_from: str = "noreply@vaultchain.example"
    resend_api_key: SecretStr | None = None
    #: Public origin of the user-facing app. Magic-link URLs interpolate
    #: this — see AC-phase1-identity-002-10. Production sets it to e.g.
    #: ``https://app.vaultchain.io``; CI defaults remain http://localhost.
    frontend_url: str = "http://localhost:5173"

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

    @model_validator(mode="after")
    def _inject_db_password(self) -> Self:
        """Splice the postgres password into ``database_url`` when the URL has
        no embedded password.

        Prod compose sets ``DATABASE_URL=postgresql+asyncpg://vaultchain@postgres:5432/vaultchain``
        (no password) and mounts the password as a docker secret at
        ``/run/secrets/postgres_password``.

        Resolution order for the password:
        1. ``self.postgres_password`` populated via pydantic-settings
           ``secrets_dir`` reading the same file.
        2. Direct read of ``/run/secrets/postgres_password`` — defensive
           fallback in case pydantic-settings doesn't pick it up (different
           v2.x versions strip whitespace differently; the brief assumes the
           file is the source of truth).

        Dev / CI / test envs bake the password into DATABASE_URL directly, so
        this is a no-op there (the password check on the parsed URL skips).
        """
        if not self.database_url:
            return self
        url = make_url(self.database_url)
        if url.password:
            return self  # URL already has password (dev/test path)

        password: str | None = None
        if self.postgres_password:
            password = self.postgres_password.get_secret_value()
        if not password:
            from pathlib import Path

            pw_file = Path("/run/secrets/postgres_password")
            if pw_file.is_file():
                password = pw_file.read_text().strip() or None
        if password:
            # `str(url)` masks the password as ``***`` for safe logging; we
            # need the real value so asyncpg can authenticate.
            self.database_url = url.set(password=password).render_as_string(hide_password=False)
        return self


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
