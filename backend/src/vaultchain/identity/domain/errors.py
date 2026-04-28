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


class MagicLinkInvalid(DomainError):
    """Token hash matches no row; AC-phase1-identity-002-06."""

    code: ClassVar[str] = "identity.magic_link_invalid"
    status_code: ClassVar[int] = HTTPStatus.UNAUTHORIZED
    default_message: ClassVar[str] = "Magic link is invalid."


class MagicLinkExpired(DomainError):
    """Magic link's `expires_at` is in the past; AC-phase1-identity-002-08.

    Status is 401 (not 410): per the brief, expired / unknown / already
    used all map to 401 so that response distinguishability does not
    leak whether a particular token ever existed.
    """

    code: ClassVar[str] = "identity.magic_link_expired"
    status_code: ClassVar[int] = HTTPStatus.UNAUTHORIZED
    default_message: ClassVar[str] = "Magic link has expired."


class MagicLinkAlreadyUsed(DomainError):
    """Magic link's `consumed_at` is already set; AC-phase1-identity-002-07."""

    code: ClassVar[str] = "identity.magic_link_already_used"
    status_code: ClassVar[int] = HTTPStatus.UNAUTHORIZED
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


class Unauthenticated(DomainError):
    """No valid session for the request; AC-phase1-identity-004-03."""

    code: ClassVar[str] = "identity.unauthenticated"
    status_code: ClassVar[int] = HTTPStatus.UNAUTHORIZED
    default_message: ClassVar[str] = "Authentication required."


class RefreshTokenInvalid(DomainError):
    """Refresh token does not match an active session; AC-phase1-identity-004-05/06.

    The same code is raised for unknown / revoked / expired refresh tokens
    on purpose — differentiating leaks information to attackers.
    """

    code: ClassVar[str] = "identity.refresh_token_invalid"
    status_code: ClassVar[int] = HTTPStatus.UNAUTHORIZED
    default_message: ClassVar[str] = "Refresh token is invalid or expired."


class CsrfFailed(_SharedPermissionError):
    """Double-submit cookie / header mismatch on a mutating request."""

    code: ClassVar[str] = "identity.csrf_failed"
    status_code: ClassVar[int] = HTTPStatus.FORBIDDEN
    default_message: ClassVar[str] = "CSRF check failed."


__all__ = [
    "CsrfFailed",
    "InvalidStateTransition",
    "MagicLinkAlreadyUsed",
    "MagicLinkExpired",
    "MagicLinkInvalid",
    "RefreshTokenInvalid",
    "TotpAlreadyEnrolled",
    "TotpNotEnrolled",
    "Unauthenticated",
    "UserLocked",
]
