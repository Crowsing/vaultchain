"""Console-only ``EmailSender`` — V1 dev/test adapter.

Per AC-phase1-identity-002-10 the sole observable behaviour is a single
structured log line per call (subject, to, url). Production tooling
greps the line; the real provider arrives in Phase 2.
"""

from __future__ import annotations

import structlog

#: The structlog ``event`` name used by every emitted line. Tests, dev
#: tooling, and operators all key off this constant.
EMAIL_LOG_EVENT = "identity.email.magic_link"
SUBJECT = "Your VaultChain magic link"

_log = structlog.get_logger(__name__)


class ConsoleEmailSender:
    """``EmailSender`` adapter that prints a structured log line."""

    def __init__(self, *, frontend_url: str) -> None:
        # Strip a trailing slash so URL composition is unambiguous.
        self._frontend_url = frontend_url.rstrip("/")

    async def send_magic_link(
        self,
        *,
        to_email: str,
        raw_token: str,
        mode: str,
    ) -> None:
        url = f"{self._frontend_url}/auth/verify?token={raw_token}&mode={mode}"
        _log.info(
            EMAIL_LOG_EVENT,
            to=to_email,
            subject=SUBJECT,
            url=url,
            mode=mode,
        )


__all__ = ["EMAIL_LOG_EVENT", "SUBJECT", "ConsoleEmailSender"]
