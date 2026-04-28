"""Handler ``mark_user_verified_on_signup_link`` — AC-phase1-identity-002-09.

Subscribes to ``MagicLinkConsumed``; when ``mode == SIGNUP``, transitions
the user from `unverified` → `verified` and bumps the version. Handler
runs in the outbox worker so re-delivery is possible; the handler is
designed to be safely re-firable:

  * If the user is gone (deleted), no-op (warn-log).
  * If the user is already verified, the ``User.verify_email`` raises
    ``InvalidStateTransition`` — caught and treated as success.

The outbox publisher's `event_handler_log` table provides the strong
'at-most-once delivery' guarantee at the storage layer; this in-handler
defence is the second line for tests, in-process pumps, and any future
direct callers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from vaultchain.identity.domain.aggregates import MagicLinkMode
from vaultchain.identity.domain.errors import InvalidStateTransition
from vaultchain.identity.domain.events import MagicLinkConsumed
from vaultchain.identity.domain.ports import UserRepository
from vaultchain.shared.events.base import DomainEvent
from vaultchain.shared.events.bus import EventBus
from vaultchain.shared.unit_of_work import AbstractUnitOfWork

_log = logging.getLogger(__name__)


def make_signup_verification_handler(
    *,
    uow_factory: Callable[[], AbstractUnitOfWork],
    users: Callable[[Any], UserRepository],
) -> Callable[[DomainEvent], Any]:
    """Build a ``MagicLinkConsumed`` handler bound to the supplied UoW + repos.

    Returned coroutine is registered with the bus via
    ``register_signup_verification_handler``. If you need to drive it
    directly (tests), call the return value of this factory.
    """

    async def mark_user_verified_on_signup_link(event: DomainEvent) -> None:
        if not isinstance(event, MagicLinkConsumed):
            return  # mis-routed; bus filters by event_type, but be defensive
        if event.mode is not MagicLinkMode.SIGNUP:
            # login-mode consume doesn't touch user status; no-op.
            return

        async with uow_factory() as uow:
            user = await users(uow.session).get_by_id(event.user_id)
            if user is None:
                # User vanished between consume + handler dispatch. The
                # cleanest treatment is a warn-log no-op so the outbox
                # marks the row published and stops retrying.
                _log.warning(
                    "identity.signup_verification_handler.user_missing",
                    extra={"user_id": str(event.user_id)},
                )
                return

            try:
                user.verify_email()
            except InvalidStateTransition:
                # Already verified (or locked — locked is unexpected here
                # because lockout is TOTP-bound; treat as terminal anyway).
                # End state matches our intent; commit nothing extra.
                return

            await users(uow.session).update(user)
            for evt in user.pull_events():
                uow.add_event(evt)
            await uow.commit()

    return mark_user_verified_on_signup_link


# Stable handler symbol so the outbox idempotency log can identify it
# via ``__qualname__`` even when the closure is rebuilt.
async def mark_user_verified_on_signup_link(event: DomainEvent) -> None:
    """Module-level placeholder — composition root replaces it via
    ``register_signup_verification_handler`` so the outbox can persist
    a stable handler name in ``shared.event_handler_log``.
    """
    raise RuntimeError(
        "Signup-verification handler not wired; call "
        "register_signup_verification_handler(...) first"
    )


def register_signup_verification_handler(
    *,
    bus: EventBus,
    uow_factory: Callable[[], AbstractUnitOfWork],
    users: Callable[[Any], UserRepository],
) -> Callable[[DomainEvent], Any]:
    """Wire the handler into ``bus`` for ``MagicLinkConsumed``.

    Returns the bound coroutine so callers (or tests) can drive it
    directly. Calling more than once on the same bus is an error.
    """
    bound = make_signup_verification_handler(uow_factory=uow_factory, users=users)
    bound.__qualname__ = "mark_user_verified_on_signup_link"
    bus.subscribe(MagicLinkConsumed.event_type, bound)
    return bound


__all__ = [
    "make_signup_verification_handler",
    "mark_user_verified_on_signup_link",
    "register_signup_verification_handler",
]
