"""composition._build_email_sender — adapter selection contract.

Production sets RESEND_API_KEY → ResendEmailSender. Dev/CI leave it unset
→ ConsoleEmailSender. The selection is the only seam where the ``RESEND_API_KEY``
secret turns into actual outbound email delivery; getting it wrong silently
disables magic-link emails (the V1 console adapter only logs).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from vaultchain.config import Settings, reset_settings_cache
from vaultchain.identity.delivery.composition import _build_email_sender
from vaultchain.identity.infra.email.console import ConsoleEmailSender
from vaultchain.identity.infra.email.resend import ResendEmailSender


@pytest.fixture
def _isolate_env() -> Iterator[None]:
    saved = dict(os.environ)
    reset_settings_cache()
    yield
    os.environ.clear()
    os.environ.update(saved)
    reset_settings_cache()


def _base_env() -> dict[str, str]:
    return {
        "ENVIRONMENT": "test",
        "SECRET_KEY": "test-secret-key-32-chars-minimum-aaaa",
        "DATABASE_URL": "postgresql+asyncpg://x:y@localhost:5432/z",
        "REDIS_URL": "redis://localhost:6379/0",
    }


@pytest.mark.usefixtures("_isolate_env")
def test_console_sender_when_resend_api_key_unset() -> None:
    os.environ.update(_base_env())
    os.environ.pop("RESEND_API_KEY", None)

    sender = _build_email_sender(Settings())

    assert isinstance(sender, ConsoleEmailSender)


@pytest.mark.usefixtures("_isolate_env")
def test_resend_sender_when_resend_api_key_present() -> None:
    os.environ.update(_base_env())
    os.environ["RESEND_API_KEY"] = "re_prod_xxxxxxxx"
    os.environ["EMAIL_FROM"] = "VaultChain <noreply@example.com>"
    os.environ["FRONTEND_URL"] = "https://app.example.com"

    sender = _build_email_sender(Settings())

    assert isinstance(sender, ResendEmailSender)
