"""ConsoleEmailSender adapter tests — AC-phase1-identity-002-10.

The console adapter is the V1 EmailSender; its only contract is to emit
a single structured log line per call so dev tooling can grep it. The
real Resend/Postmark adapter slots in via DI in Phase 2 — same port,
different implementation.
"""

from __future__ import annotations

import pytest
import structlog
from structlog.testing import LogCapture

from vaultchain.identity.infra.email.console import (
    EMAIL_LOG_EVENT,
    ConsoleEmailSender,
)


@pytest.fixture
def captured_log() -> LogCapture:
    cap = LogCapture()
    old_config = structlog.get_config().copy()
    structlog.configure(processors=[cap])
    yield cap
    structlog.configure(**old_config)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ac_10_console_email_sender_emits_structured_line_signup(
    captured_log: LogCapture,
) -> None:
    sender = ConsoleEmailSender(frontend_url="https://app.example")

    await sender.send_magic_link(to_email="user@x.io", raw_token="tok-abc", mode="signup")

    matching = [c for c in captured_log.entries if c.get("event") == EMAIL_LOG_EVENT]
    assert len(matching) == 1
    line = matching[0]
    assert line["to"] == "user@x.io"
    assert line["mode"] == "signup"
    assert line["url"] == "https://app.example/auth/verify?token=tok-abc&mode=signup"
    assert line["subject"] == "Your VaultChain magic link"


@pytest.mark.asyncio
async def test_ac_10_console_email_sender_login_mode_url(captured_log: LogCapture) -> None:
    sender = ConsoleEmailSender(frontend_url="https://app.example")

    await sender.send_magic_link(to_email="returning@x.io", raw_token="tok-xyz", mode="login")

    line = next(c for c in captured_log.entries if c.get("event") == EMAIL_LOG_EVENT)
    assert line["url"] == "https://app.example/auth/verify?token=tok-xyz&mode=login"


@pytest.mark.asyncio
async def test_ac_10_console_email_sender_strips_trailing_slash_on_frontend_url(
    captured_log: LogCapture,
) -> None:
    """Operator might set FRONTEND_URL with or without trailing slash; tolerate both."""
    sender = ConsoleEmailSender(frontend_url="https://app.example/")

    await sender.send_magic_link(to_email="x@x.io", raw_token="t1", mode="signup")

    line = next(c for c in captured_log.entries if c.get("event") == EMAIL_LOG_EVENT)
    assert "//auth/verify" not in line["url"]
    assert line["url"].endswith("/auth/verify?token=t1&mode=signup")


@pytest.mark.asyncio
async def test_ac_10_console_email_sender_emits_one_line_per_call(
    captured_log: LogCapture,
) -> None:
    sender = ConsoleEmailSender(frontend_url="https://app.example")

    await sender.send_magic_link(to_email="x@x.io", raw_token="raw-secret", mode="signup")

    matching = [c for c in captured_log.entries if c.get("event") == EMAIL_LOG_EVENT]
    assert len(matching) == 1
