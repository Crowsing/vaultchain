"""Identity event handlers — lockout counter for TOTP failures.

The handler ``increment_user_lockout_counter`` subscribes to
``TotpVerificationFailed`` and, when the threshold is reached, applies
the 15-minute lockout via ``User.lock_due_to_totp_failures``. The
handler runs in its OWN UoW with optimistic-lock retry on
``StaleAggregate`` (per the brief Risk/Friction note).

The verify use case already increments ``failed_totp_attempts``;
this handler reads the persisted state to make the lock decision and
captures the ``UserLockedDueToTotpFailures`` event.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from vaultchain.identity.domain.aggregates import TOTP_LOCKOUT_THRESHOLD
from vaultchain.identity.domain.events import TotpVerificationFailed
from vaultchain.identity.domain.ports import UserRepository
from vaultchain.shared.domain.errors import StaleAggregate
from vaultchain.shared.events.base import DomainEvent
from vaultchain.shared.events.bus import EventBus
from vaultchain.shared.unit_of_work import AbstractUnitOfWork

_log = logging.getLogger(__name__)
_MAX_RETRIES = 3


def make_lockout_handler(
    *,
    uow_factory: Callable[[], AbstractUnitOfWork],
    users: Callable[[Any], UserRepository],
) -> Callable[[DomainEvent], Any]:
    """Build a `TotpVerificationFailed` handler bound to the given UoW + repos.

    Returned coroutine is registered with the bus via
    ``register_lockout_handler``. Concurrent failures from the same user
    are handled by optimistic-lock retry; a `StaleAggregate` raised
    from the User repository ``update`` is treated as a cue to re-read
    and re-decide.
    """

    async def increment_user_lockout_counter(event: DomainEvent) -> None:
        if not isinstance(event, TotpVerificationFailed):
            return  # mis-routed; bus filters by event_type, but be defensive
        for attempt in range(_MAX_RETRIES):
            async with uow_factory() as uow:
                user = await users(uow.session).get_by_id(event.user_id)
                if user is None:
                    _log.warning("identity.lockout_handler.user_missing")
                    return
                if user.is_locked_now():
                    return  # already locked — no work to do
                if user.failed_totp_attempts < TOTP_LOCKOUT_THRESHOLD:
                    return  # below threshold — handler is a no-op
                user.lock_due_to_totp_failures()
                for evt in user.pull_events():
                    uow.add_event(evt)
                try:
                    await users(uow.session).update(user)
                    await uow.commit()
                    return
                except StaleAggregate:
                    if attempt + 1 == _MAX_RETRIES:
                        raise
                    continue
        # exhausted retries
        raise StaleAggregate(
            details={"user_id": str(event.user_id), "kind": "user", "retries": _MAX_RETRIES}
        )

    return increment_user_lockout_counter


# Stable handler symbol so the outbox publisher's idempotency log can
# identify it via ``__qualname__`` even when the closure is rebuilt.
async def increment_user_lockout_counter(event: DomainEvent) -> None:
    """Module-level placeholder — composition root replaces it via
    ``register_lockout_handler`` so the outbox can persist a stable
    handler name in ``shared.event_handler_log``.
    """
    raise RuntimeError("Lockout handler not wired; call register_lockout_handler(...) first")


def register_lockout_handler(
    *,
    bus: EventBus,
    uow_factory: Callable[[], AbstractUnitOfWork],
    users: Callable[[Any], UserRepository],
) -> Callable[[DomainEvent], Any]:
    """Wire the lockout handler into ``bus`` for ``TotpVerificationFailed``.

    Returns the bound coroutine so callers (or tests) can drive it
    directly. Calling more than once on the same bus is an error.
    """
    bound = make_lockout_handler(uow_factory=uow_factory, users=users)
    # Preserve a stable __qualname__ for the outbox idempotency ledger.
    bound.__qualname__ = "increment_user_lockout_counter"
    bus.subscribe(TotpVerificationFailed.event_type, bound)
    return bound


__all__ = [
    "increment_user_lockout_counter",
    "make_lockout_handler",
    "register_lockout_handler",
]
