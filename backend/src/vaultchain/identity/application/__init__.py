"""Identity application layer — use cases + event handlers.

Use cases coordinate aggregates, ports, and the UoW; they raise
domain errors and return DTOs. The lockout-counter handler subscribes
to ``TotpVerificationFailed`` and applies the lockout transition via
its own UoW (per AC-phase1-identity-003-06).

Session-management use cases (phase1-identity-004) live next to the
TOTP use cases; the FastAPI request dependencies live in
``vaultchain.identity.delivery.dependencies``.
"""

from vaultchain.identity.application.create_session import (
    ACCESS_TOKEN_TTL,
    DEFAULT_SCOPES,
    REFRESH_TOKEN_TTL,
    CreateSession,
    CreateSessionResult,
)
from vaultchain.identity.application.enroll_totp import (
    EnrollTotp,
    TotpEnrollmentResult,
)
from vaultchain.identity.application.handlers import (
    increment_user_lockout_counter,
    register_lockout_handler,
)
from vaultchain.identity.application.refresh_session import (
    RefreshSession,
    RefreshSessionResult,
)
from vaultchain.identity.application.regenerate_backup_codes import (
    BackupCodesRegenerationResult,
    RegenerateBackupCodes,
)
from vaultchain.identity.application.revoke_session import (
    RevokeAllSessions,
    RevokeSession,
    RevokeSessionResult,
)
from vaultchain.identity.application.verify_totp import (
    TotpVerifyResult,
    VerifyTotp,
)

__all__ = [
    "ACCESS_TOKEN_TTL",
    "DEFAULT_SCOPES",
    "REFRESH_TOKEN_TTL",
    "BackupCodesRegenerationResult",
    "CreateSession",
    "CreateSessionResult",
    "EnrollTotp",
    "RefreshSession",
    "RefreshSessionResult",
    "RegenerateBackupCodes",
    "RevokeAllSessions",
    "RevokeSession",
    "RevokeSessionResult",
    "TotpEnrollmentResult",
    "TotpVerifyResult",
    "VerifyTotp",
    "increment_user_lockout_counter",
    "register_lockout_handler",
]
