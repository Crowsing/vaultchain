"""``ConsumeMagicLink`` use case — AC-phase1-identity-002-05..08.

Looks up the magic link by sha256 of the raw token (constant-time
compared via the unique-index lookup), enforces lifecycle invariants
on the aggregate (`MagicLink.consume()` raises on already-used /
expired), persists the consumed_at update, captures the
``MagicLinkConsumed`` event.

The use case does NOT mutate the user — that's the
``mark_user_verified_on_signup_link`` handler's job (AC-09), which
runs in the outbox worker so re-delivery is idempotent.

Returns ``MagicLinkConsumeResult`` with an ``is_first_time`` flag the
HTTP/route layer (identity-005) consumes to decide whether the user
goes to TOTP enrollment or TOTP login. The flag is derived from
``TotpSecretRepository.get_by_user_id IS None`` rather than the
link's ``mode`` so re-takings of the flow remain accurate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from vaultchain.identity.domain.aggregates import MagicLinkMode
from vaultchain.identity.domain.errors import MagicLinkInvalid
from vaultchain.identity.domain.events import MagicLinkConsumed
from vaultchain.identity.domain.ports import (
    MagicLinkRepository,
    TotpSecretRepository,
    UserRepository,
)
from vaultchain.identity.infra.tokens.hashing import sha256_bytes
from vaultchain.shared.unit_of_work import AbstractUnitOfWork


@dataclass(frozen=True)
class MagicLinkConsumeResult:
    user_id: UUID
    mode: MagicLinkMode
    is_first_time: bool


class ConsumeMagicLink:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        users: Callable[[Any], UserRepository],
        magic_links: Callable[[Any], MagicLinkRepository],
        totp_secrets: Callable[[Any], TotpSecretRepository],
    ) -> None:
        self._uow_factory = uow_factory
        self._users = users
        self._magic_links = magic_links
        self._totp_secrets = totp_secrets

    async def execute(
        self,
        *,
        raw_token: str,
        user_agent: str = "",
        ip: str | None = None,
    ) -> MagicLinkConsumeResult:
        token_hash = sha256_bytes(raw_token)

        async with self._uow_factory() as uow:
            link = await self._magic_links(uow.session).get_by_token_hash(token_hash)
            if link is None:
                raise MagicLinkInvalid(details={"reason": "unknown_token"})

            # `link.consume()` raises MagicLinkAlreadyUsed / MagicLinkExpired
            # — both with status 401 per the brief. Those bubble out without
            # mutating the row so the database remains consistent.
            link.consume()
            await self._magic_links(uow.session).update(link)

            uow.add_event(
                MagicLinkConsumed(
                    aggregate_id=link.id,
                    user_id=link.user_id,
                    mode=link.mode,
                )
            )

            # Determine first-time-ness *inside* the UoW so it observes the
            # same DB snapshot as the consume.
            totp = await self._totp_secrets(uow.session).get_by_user_id(link.user_id)
            is_first_time = totp is None

            await uow.commit()

        # `user_agent` and `ip` are not stored on the link itself; they are
        # available here so future audit logging (identity-005) can record
        # them in the request-level structured log without re-reading.
        _ = user_agent
        _ = ip

        return MagicLinkConsumeResult(
            user_id=link.user_id, mode=link.mode, is_first_time=is_first_time
        )


__all__ = ["ConsumeMagicLink", "MagicLinkConsumeResult"]
