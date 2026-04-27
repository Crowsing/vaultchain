"""Backend test fixtures.

Provides session-scoped stubs for tests that don't need real services.
Phase 1+ briefs replace these with real testcontainers-driven fixtures.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Default test env so config.py instantiates cleanly without external services.
_TEST_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/vaultchain_test",
    "REDIS_URL": "redis://localhost:6379/1",
    "ENVIRONMENT": "test",
    "SECRET_KEY": "test-secret-key-32-chars-minimum-aaaa",
    "TELEGRAM_BOT_TOKEN": "test-telegram-token",
    "TELEGRAM_CHAT_ID": "test-chat-id",
}

# Apply at conftest import time so test modules can import vaultchain.main
# (which instantiates Settings at module level) without ValidationErrors.
for _k, _v in _TEST_ENV.items():
    os.environ.setdefault(_k, _v)


@pytest.fixture(autouse=True, scope="session")
def _set_test_env() -> Iterator[None]:
    saved: dict[str, str | None] = {k: os.environ.get(k) for k in _TEST_ENV}
    for k, v in _TEST_ENV.items():
        os.environ.setdefault(k, v)
    yield
    for k, original in saved.items():
        if original is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = original
