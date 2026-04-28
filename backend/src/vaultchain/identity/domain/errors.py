"""Identity-specific domain errors."""

from __future__ import annotations

from http import HTTPStatus
from typing import ClassVar

from vaultchain.shared.domain.errors import ConflictError, DomainError


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


__all__ = [
    "InvalidStateTransition",
    "MagicLinkAlreadyUsed",
    "MagicLinkExpired",
]
