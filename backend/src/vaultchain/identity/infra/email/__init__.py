"""Identity email infrastructure.

V1 ships ``ConsoleEmailSender`` only. The Resend/Postmark adapter
arrives in Phase 2 and slots in via DI on the same ``EmailSender`` port.
"""

from __future__ import annotations

from vaultchain.identity.infra.email.console import ConsoleEmailSender

__all__ = ["ConsoleEmailSender"]
