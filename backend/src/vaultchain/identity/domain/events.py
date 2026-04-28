"""Identity domain events.

Declared here as dataclasses; *not* registered into `event_registry` until
the use-case briefs (identity-002/003/004) wire emitting handlers, per the
brief Done Definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar
from uuid import UUID

from vaultchain.shared.events.base import DomainEvent
from vaultchain.shared.events.registry import register_event


@dataclass(frozen=True, kw_only=True)
class UserSignedUp(DomainEvent):
    email: str
    aggregate_type: ClassVar[str] = "user"
    event_type: ClassVar[str] = "identity.user_signed_up"


@dataclass(frozen=True, kw_only=True)
class UserLocked(DomainEvent):
    reason: str = ""
    aggregate_type: ClassVar[str] = "user"
    event_type: ClassVar[str] = "identity.user_locked"


@dataclass(frozen=True, kw_only=True)
class MagicLinkRequested(DomainEvent):
    user_id: UUID
    mode: str
    aggregate_type: ClassVar[str] = "magic_link"
    event_type: ClassVar[str] = "identity.magic_link_requested"


@dataclass(frozen=True, kw_only=True)
class MagicLinkConsumed(DomainEvent):
    user_id: UUID
    mode: str
    aggregate_type: ClassVar[str] = "magic_link"
    event_type: ClassVar[str] = "identity.magic_link_consumed"


@register_event
@dataclass(frozen=True, kw_only=True)
class TotpEnrolled(DomainEvent):
    user_id: UUID
    aggregate_type: ClassVar[str] = "totp_secret"
    event_type: ClassVar[str] = "identity.totp_enrolled"


@register_event
@dataclass(frozen=True, kw_only=True)
class TotpVerified(DomainEvent):
    user_id: UUID
    last_verified_at: datetime
    aggregate_type: ClassVar[str] = "totp_secret"
    event_type: ClassVar[str] = "identity.totp_verified"


@register_event
@dataclass(frozen=True, kw_only=True)
class TotpVerificationFailed(DomainEvent):
    """Captured per failed TOTP attempt; the lockout handler subscribes."""

    user_id: UUID
    failed_attempts: int
    aggregate_type: ClassVar[str] = "user"
    event_type: ClassVar[str] = "identity.totp_verification_failed"


@register_event
@dataclass(frozen=True, kw_only=True)
class UserLockedDueToTotpFailures(DomainEvent):
    """Captured by the User aggregate when the lockout transition fires."""

    locked_until: datetime
    aggregate_type: ClassVar[str] = "user"
    event_type: ClassVar[str] = "identity.user_locked_due_to_totp_failures"


@register_event
@dataclass(frozen=True, kw_only=True)
class SessionCreated(DomainEvent):
    user_id: UUID
    aggregate_type: ClassVar[str] = "session"
    event_type: ClassVar[str] = "identity.session_created"


@register_event
@dataclass(frozen=True, kw_only=True)
class SessionRefreshed(DomainEvent):
    """Refresh token rotated in place — same session id, fresh hash."""

    user_id: UUID
    aggregate_type: ClassVar[str] = "session"
    event_type: ClassVar[str] = "identity.session_refreshed"


@register_event
@dataclass(frozen=True, kw_only=True)
class SessionRevoked(DomainEvent):
    user_id: UUID
    aggregate_type: ClassVar[str] = "session"
    event_type: ClassVar[str] = "identity.session_revoked"


# Pulling `field` so import-organizers don't drop it; subclasses below may
# add fields with defaults via `field(default_factory=...)` if extended.
_ = field


__all__ = [
    "MagicLinkConsumed",
    "MagicLinkRequested",
    "SessionCreated",
    "SessionRefreshed",
    "SessionRevoked",
    "TotpEnrolled",
    "TotpVerificationFailed",
    "TotpVerified",
    "UserLocked",
    "UserLockedDueToTotpFailures",
    "UserSignedUp",
]
