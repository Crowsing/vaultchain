"""Identity domain layer — entities, VOs, ports, events, errors."""

from vaultchain.identity.domain.aggregates import (
    MagicLink,
    MagicLinkMode,
    Session,
    TotpSecret,
    User,
    UserStatus,
)
from vaultchain.identity.domain.errors import (
    InvalidStateTransition,
    MagicLinkAlreadyUsed,
    MagicLinkExpired,
)
from vaultchain.identity.domain.value_objects import Email

__all__ = [
    "Email",
    "InvalidStateTransition",
    "MagicLink",
    "MagicLinkAlreadyUsed",
    "MagicLinkExpired",
    "MagicLinkMode",
    "Session",
    "TotpSecret",
    "User",
    "UserStatus",
]
