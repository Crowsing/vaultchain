"""Identity aggregate roots: User, Session, MagicLink, TotpSecret.

All four are flat (no child entities in V1). Aggregate methods enforce state
machine invariants and append events to a per-aggregate `_pending_events`
buffer; the calling use case retrieves them via `pull_events()` and adds
them to the UoW (which then writes them atomically to `shared.domain_events`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from uuid import UUID, uuid4

from vaultchain.identity.domain.errors import (
    InvalidStateTransition,
    MagicLinkAlreadyUsed,
    MagicLinkExpired,
)

if TYPE_CHECKING:
    from vaultchain.identity.domain.ports import TotpSecretEncryptor
    from vaultchain.shared.events.base import DomainEvent


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UserStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    LOCKED = "locked"


class MagicLinkMode(StrEnum):
    """Magic-link request kind. Same string values the brief calls out
    so wire-format and tests stay readable.
    """

    SIGNUP = "signup"
    LOGIN = "login"


#: Wrong TOTP attempts permitted before the lockout transition fires.
TOTP_LOCKOUT_THRESHOLD: Final[int] = 5
#: Self-healing lockout window per AC-phase1-identity-003-06/07.
TOTP_LOCKOUT_WINDOW: Final[timedelta] = timedelta(minutes=15)


@dataclass
class User:
    id: UUID
    email: str
    email_hash: bytes
    status: UserStatus = UserStatus.UNVERIFIED
    kyc_tier: int = 0
    version: int = 0
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime | None = None
    failed_totp_attempts: int = 0
    locked_until: datetime | None = None
    _pending_events: list[DomainEvent] = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def signup(cls, *, email: str, email_hash: bytes, user_id: UUID | None = None) -> User:
        from vaultchain.identity.domain.events import UserSignedUp

        uid = user_id or uuid4()
        u = cls(id=uid, email=email, email_hash=email_hash)
        u._pending_events.append(UserSignedUp(aggregate_id=uid, email=email))
        return u

    def verify_email(self) -> None:
        if self.status == UserStatus.VERIFIED:
            raise InvalidStateTransition(
                details={"from": self.status.value, "to": UserStatus.VERIFIED.value}
            )
        if self.status == UserStatus.LOCKED:
            raise InvalidStateTransition(
                details={"from": self.status.value, "to": UserStatus.VERIFIED.value}
            )
        self.status = UserStatus.VERIFIED
        self.version += 1
        self.updated_at = _utc_now()

    def lock(self, reason: str = "") -> None:
        from vaultchain.identity.domain.events import UserLocked

        self.status = UserStatus.LOCKED
        self.version += 1
        self.updated_at = _utc_now()
        self._pending_events.append(UserLocked(aggregate_id=self.id, reason=reason))

    def record_totp_failure(self, *, now: datetime | None = None) -> None:
        """Increment the TOTP failure counter (state-only; no event emitted).

        The lockout transition is owned by ``lock_due_to_totp_failures``,
        which the lockout-handler invokes when the threshold is reached.
        Per the brief, going through the event bus keeps the transition
        observable.
        """
        self.failed_totp_attempts += 1
        self.version += 1
        self.updated_at = now or _utc_now()

    def lock_due_to_totp_failures(self, *, now: datetime | None = None) -> None:
        """Apply the 15-min self-healing lockout (AC-phase1-identity-003-06).

        Idempotent: re-invoking while ``is_locked_now()`` is True is a no-op.
        Raises if the threshold has not been reached, so we don't paper over
        a wiring bug in the handler.
        """
        from vaultchain.identity.domain.events import UserLockedDueToTotpFailures

        moment = now or _utc_now()
        if self.is_locked_now(now=moment):
            return
        if self.failed_totp_attempts < TOTP_LOCKOUT_THRESHOLD:
            raise InvalidStateTransition(
                details={
                    "from": self.status.value,
                    "reason": "totp_failure_threshold_not_reached",
                    "failed_totp_attempts": self.failed_totp_attempts,
                }
            )
        self.locked_until = moment + TOTP_LOCKOUT_WINDOW
        self.status = UserStatus.LOCKED
        self.version += 1
        self.updated_at = moment
        self._pending_events.append(
            UserLockedDueToTotpFailures(
                aggregate_id=self.id,
                locked_until=self.locked_until,
            )
        )

    def is_locked_now(self, *, now: datetime | None = None) -> bool:
        if self.locked_until is None:
            return False
        return self.locked_until > (now or _utc_now())

    def clear_totp_failures(self, *, now: datetime | None = None) -> None:
        """Reset the lockout state machine on a successful verification.

        Used both by the standard success path (resets a non-zero counter)
        and the self-healing path (AC-phase1-identity-003-07: lockout window
        elapsed → counter cleared and the user becomes verified again).
        No-op when already clean.
        """
        if self.failed_totp_attempts == 0 and self.locked_until is None:
            return
        was_locked = self.status is UserStatus.LOCKED
        self.failed_totp_attempts = 0
        self.locked_until = None
        if was_locked:
            self.status = UserStatus.VERIFIED
        self.version += 1
        self.updated_at = now or _utc_now()

    def pull_events(self) -> tuple[DomainEvent, ...]:
        out = tuple(self._pending_events)
        self._pending_events.clear()
        return out


@dataclass
class Session:
    id: UUID
    user_id: UUID
    refresh_token_hash: bytes
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    user_agent: str = ""
    ip_inet: str | None = None
    version: int = 0

    def is_active(self, *, now: datetime | None = None) -> bool:
        moment = now or _utc_now()
        if self.revoked_at is not None:
            return False
        return self.expires_at > moment

    def revoke(self, *, now: datetime | None = None) -> None:
        if self.revoked_at is not None:
            return  # idempotent
        self.revoked_at = now or _utc_now()
        self.version += 1


@dataclass
class MagicLink:
    id: UUID
    user_id: UUID
    token_hash: bytes
    mode: MagicLinkMode
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None

    def consume(self, *, now: datetime | None = None) -> None:
        moment = now or _utc_now()
        if self.consumed_at is not None:
            raise MagicLinkAlreadyUsed(details={"magic_link_id": str(self.id)})
        if self.expires_at <= moment:
            raise MagicLinkExpired(details={"magic_link_id": str(self.id)})
        self.consumed_at = moment


@dataclass
class TotpSecret:
    id: UUID
    user_id: UUID
    secret_encrypted: bytes
    backup_codes_hashed: list[bytes]
    enrolled_at: datetime
    last_verified_at: datetime | None = None

    @classmethod
    def enroll(
        cls,
        *,
        user_id: UUID,
        secret_plain: bytes,
        backup_codes_hashed: list[bytes],
        encryptor: TotpSecretEncryptor,
        secret_id: UUID | None = None,
    ) -> TotpSecret:
        encrypted = encryptor.encrypt(secret_plain)
        return cls(
            id=secret_id or uuid4(),
            user_id=user_id,
            secret_encrypted=encrypted,
            backup_codes_hashed=list(backup_codes_hashed),
            enrolled_at=_utc_now(),
        )

    def decrypt(self, encryptor: TotpSecretEncryptor) -> bytes:
        return encryptor.decrypt(self.secret_encrypted)


__all__ = [
    "TOTP_LOCKOUT_THRESHOLD",
    "TOTP_LOCKOUT_WINDOW",
    "MagicLink",
    "MagicLinkMode",
    "Session",
    "TotpSecret",
    "User",
    "UserStatus",
]
