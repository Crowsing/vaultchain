"""Identity-specific domain errors."""

from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from vaultchain.shared.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
)
from vaultchain.shared.domain.errors import (
    PermissionError as _SharedPermissionError,
)


class InvalidStateTransition(ConflictError):
    """Aggregate state-machine transition is not allowed from current state."""

    code: ClassVar[str] = "identity.invalid_state_transition"
    status_code: ClassVar[int] = HTTPStatus.CONFLICT
    default_message: ClassVar[str] = "Invalid state transition for this aggregate."


class MagicLinkExpired(DomainError):
    """Magic link's `expires_at` is in the past."""

    code: ClassVar[str] = "identity.magic_link_expired"
    status_code: ClassVar[int] = HTTPStatus.GONE
    default_message: ClassVar[str] = "Magic link has expired."


class MagicLinkAlreadyUsed(DomainError):
    """Magic link's `consumed_at` is already set."""

    code: ClassVar[str] = "identity.magic_link_already_used"
    status_code: ClassVar[int] = HTTPStatus.CONFLICT
    default_message: ClassVar[str] = "Magic link has already been used."


class TotpAlreadyEnrolled(ConflictError):
    """Re-enrollment is blocked; AC-phase1-identity-003-03."""

    code: ClassVar[str] = "identity.totp_already_enrolled"
    status_code: ClassVar[int] = HTTPStatus.CONFLICT
    default_message: ClassVar[str] = "TOTP is already enrolled for this user."


class TotpNotEnrolled(NotFoundError):
    """Verify or regenerate without prior enrollment."""

    code: ClassVar[str] = "identity.totp_not_enrolled"
    status_code: ClassVar[int] = HTTPStatus.NOT_FOUND
    default_message: ClassVar[str] = "TOTP is not enrolled for this user."


class UserLocked(_SharedPermissionError):
    """Verification rejected during the lockout window; AC-phase1-identity-003-06."""

    code: ClassVar[str] = "identity.user_locked"
    status_code: ClassVar[int] = HTTPStatus.FORBIDDEN
    default_message: ClassVar[str] = "User is locked; try again after the lockout window."


__all__ = [
    "InvalidStateTransition",
    "MagicLinkAlreadyUsed",
    "MagicLinkExpired",
    "TotpAlreadyEnrolled",
    "TotpNotEnrolled",
    "UserLocked",
]
