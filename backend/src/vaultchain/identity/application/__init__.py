"""Identity application layer — use cases + event handlers.

Use cases coordinate aggregates, ports, and the UoW; they raise
domain errors and return DTOs. The lockout-counter handler subscribes
to ``TotpVerificationFailed`` and applies the lockout transition via
its own UoW (per AC-phase1-identity-003-06).
"""

from vaultchain.identity.application.enroll_totp import (
    EnrollTotp,
    TotpEnrollmentResult,
)
from vaultchain.identity.application.handlers import (
    increment_user_lockout_counter,
    register_lockout_handler,
)
from vaultchain.identity.application.regenerate_backup_codes import (
    BackupCodesRegenerationResult,
    RegenerateBackupCodes,
)
from vaultchain.identity.application.verify_totp import (
    TotpVerifyResult,
    VerifyTotp,
)

__all__ = [
    "BackupCodesRegenerationResult",
    "EnrollTotp",
    "RegenerateBackupCodes",
    "TotpEnrollmentResult",
    "TotpVerifyResult",
    "VerifyTotp",
    "increment_user_lockout_counter",
    "register_lockout_handler",
]
