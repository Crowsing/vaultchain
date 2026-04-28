"""``RequestMagicLink`` use case — AC-phase1-identity-002-01..04.

Given an email + mode, creates a magic-link row, sends an email with the
raw token, captures ``MagicLinkRequested`` (and ``UserSignedUp`` when a
user row is freshly created in signup mode).

The use case is *idempotent on email* — calling twice creates two
distinct rows. Both stay valid until consumed/expired so a user hitting
'Resend' does not invalidate the prior link the email client may also
deliver.

Enumeration-defence (AC-04): a login attempt for an unknown email
takes the same code path until the moment the user row is fetched;
finding nothing is treated as a no-op success. The response shape is
indistinguishable from the 'email exists' path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from vaultchain.identity.domain.aggregates import (
    MagicLink,
    MagicLinkMode,
    User,
    UserStatus,
)
from vaultchain.identity.domain.errors import UserLocked
from vaultchain.identity.domain.events import (
    MagicLinkRequested,
    UserSignedUp,
)
from vaultchain.identity.domain.ports import (
    EmailSender,
    MagicLinkRepository,
    MagicLinkTokenGenerator,
    UserRepository,
)
from vaultchain.identity.domain.value_objects import Email
from vaultchain.identity.infra.tokens.hashing import sha256_bytes
from vaultchain.shared.unit_of_work import AbstractUnitOfWork

#: 15 minutes per the brief Context.
MAGIC_LINK_TTL = timedelta(minutes=15)

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestMagicLinkResult:
    """The response shape is intentionally minimal: enumeration-defence
    (AC-04) requires the unknown-email branch to look identical.
    """

    accepted: bool


class RequestMagicLink:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        users: Callable[[Any], UserRepository],
        magic_links: Callable[[Any], MagicLinkRepository],
        emails: EmailSender,
        token_gen: MagicLinkTokenGenerator,
    ) -> None:
        self._uow_factory = uow_factory
        self._users = users
        self._magic_links = magic_links
        self._emails = emails
        self._token_gen = token_gen

    async def execute(
        self,
        *,
        email: str,
        mode: MagicLinkMode | str,
    ) -> RequestMagicLinkResult:
        # Tolerate raw-string callers (HTTP layer pulls a `mode` field as
        # plain str). Coerce to the enum here so internal code stays typed.
        mode_enum = MagicLinkMode(mode) if not isinstance(mode, MagicLinkMode) else mode

        normalized = Email(email)
        # Always do the urlsafe work so timing is uniform across branches
        # (do not optimize this away for the unknown path — see AC-04).
        raw_token = self._token_gen.generate()

        async with self._uow_factory() as uow:
            user = await self._users(uow.session).get_by_email(normalized.value)

            if user is None and mode_enum is MagicLinkMode.LOGIN:
                # Enumeration-defence: respond with success and no side
                # effects. Log a warning so security tooling can spot
                # bursts; the log is not a contract.
                _log.warning(
                    "identity.login_request_for_unknown_email",
                    extra={"email_hash": normalized.hash_blake2b().hex()},
                )
                await uow.commit()
                return RequestMagicLinkResult(accepted=True)

            if user is not None and user.status is UserStatus.LOCKED:
                raise UserLocked(
                    details={
                        "user_id": str(user.id),
                        "locked_until": user.locked_until.isoformat()
                        if user.locked_until
                        else None,
                    }
                )

            if user is None:
                # mode == SIGNUP, new email — create the user row.
                user = User.signup(email=normalized.value, email_hash=normalized.hash_blake2b())
                await self._users(uow.session).add(user)
                for evt in user.pull_events():
                    uow.add_event(evt)
                # The signup user is freshly UserStatus.UNVERIFIED;
                # nothing else happens to it here — the
                # MagicLinkConsumed handler transitions to verified
                # asynchronously per AC-09.

            now = datetime.now(UTC)
            link = MagicLink(
                id=uuid4(),
                user_id=user.id,
                token_hash=sha256_bytes(raw_token),
                mode=mode_enum,
                created_at=now,
                expires_at=now + MAGIC_LINK_TTL,
                consumed_at=None,
            )
            await self._magic_links(uow.session).add(link)
            uow.add_event(
                MagicLinkRequested(
                    aggregate_id=link.id,
                    user_id=user.id,
                    mode=mode_enum,
                )
            )
            await uow.commit()

        # Send the email AFTER commit so a transient SMTP/console issue
        # does not roll back the magic-link row. If the send fails, the
        # link still exists; the user can retry.
        await self._emails.send_magic_link(
            to_email=normalized.value, raw_token=raw_token, mode=mode_enum.value
        )
        return RequestMagicLinkResult(accepted=True)


__all__ = [
    "MAGIC_LINK_TTL",
    "RequestMagicLink",
    "RequestMagicLinkResult",
]


# Touching `UserSignedUp` for IDE imports stability — it's pulled in
# transitively via `User.signup` adding the event to the user's pending list.
_ = UserSignedUp
