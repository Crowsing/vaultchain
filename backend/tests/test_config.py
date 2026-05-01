"""Settings tests — focused on the prod docker-compose contract.

The interesting behavior is the ``_inject_db_password`` validator that splices
``postgres_password`` (read from ``/run/secrets/postgres_password`` via
pydantic-settings ``secrets_dir``) into a password-less ``DATABASE_URL``. Dev
URLs already carry a password and must pass through untouched.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy.engine.url import make_url

from vaultchain.config import Settings, reset_settings_cache


@pytest.fixture
def _isolate_env() -> Iterator[None]:
    """Snapshot/restore env so each test sees a clean slate."""
    saved = dict(os.environ)
    reset_settings_cache()
    yield
    os.environ.clear()
    os.environ.update(saved)
    reset_settings_cache()


def _base_env() -> dict[str, str]:
    return {
        "ENVIRONMENT": "production",
        "SECRET_KEY": "test-secret-key-32-chars-minimum-aaaa",
        "REDIS_URL": "redis://redis:6379/0",
    }


@pytest.mark.usefixtures("_isolate_env")
def test_dev_url_with_password_passes_through() -> None:
    """Dev/CI URLs already embed the password — validator must not mangle them."""
    os.environ.update(_base_env())
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://vaultchain:dev-pass@localhost:5432/vaultchain"
    )
    os.environ["POSTGRES_PASSWORD"] = "should-be-ignored"

    s = Settings()
    assert s.database_url == "postgresql+asyncpg://vaultchain:dev-pass@localhost:5432/vaultchain"


@pytest.mark.usefixtures("_isolate_env")
def test_passwordless_url_with_postgres_password_gets_injected() -> None:
    """The prod compose pattern: URL has no password, POSTGRES_PASSWORD provides it."""
    os.environ.update(_base_env())
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://vaultchain@postgres:5432/vaultchain"
    os.environ["POSTGRES_PASSWORD"] = "prod-password-from-docker-secret"

    s = Settings()
    parsed = make_url(s.database_url)
    assert parsed.username == "vaultchain"
    assert parsed.password == "prod-password-from-docker-secret"
    assert parsed.host == "postgres"
    assert parsed.database == "vaultchain"


@pytest.mark.usefixtures("_isolate_env")
def test_passwordless_url_without_postgres_password_passes_through() -> None:
    """If neither URL nor POSTGRES_PASSWORD has a password, leave URL alone.

    The connection will fail at runtime — but that's a deploy-config error
    surfaced via asyncpg, not a Settings validation error.
    """
    os.environ.update(_base_env())
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://vaultchain@postgres:5432/vaultchain"
    os.environ.pop("POSTGRES_PASSWORD", None)

    s = Settings()
    assert s.database_url == "postgresql+asyncpg://vaultchain@postgres:5432/vaultchain"
    assert s.postgres_password is None


@pytest.mark.usefixtures("_isolate_env")
def test_password_with_url_special_chars_is_quoted() -> None:
    """Passwords from ``openssl rand -hex 24`` are pure hex, but be defensive:
    if a special char ever appears it must be URL-encoded so asyncpg parses
    the URL correctly.
    """
    os.environ.update(_base_env())
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://vaultchain@postgres:5432/vaultchain"
    os.environ["POSTGRES_PASSWORD"] = "p@ss/word#1"

    s = Settings()
    parsed = make_url(s.database_url)
    assert parsed.password == "p@ss/word#1"
