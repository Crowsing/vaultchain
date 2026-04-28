"""Lockout-counter handler tests — AC-phase1-identity-003-06.

Drives the handler directly with seeded `TotpVerificationFailed`
events; asserts the User aggregate is locked once the threshold is
reached, and that the handler is a no-op below the threshold or when
the user is already locked.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.identity.fakes.fake_repositories import InMemoryUserRepository
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.handlers import (
    make_lockout_handler,
    register_lockout_handler,
)
from vaultchain.identity.domain.aggregates import (
    TOTP_LOCKOUT_THRESHOLD,
    User,
    UserStatus,
)
from vaultchain.identity.domain.events import (
    TotpVerificationFailed,
    UserLockedDueToTotpFailures,
)
from vaultchain.identity.domain.value_objects import Email
from vaultchain.shared.infra.event_bus import OutboxEventBus


def _verified_user(*, failed: int = 0) -> User:
    e = Email("lock@example.com")
    user = User.signup(email=e.value, email_hash=e.hash_blake2b())
    user.pull_events()
    user.status = UserStatus.VERIFIED
    user.failed_totp_attempts = failed
    return user


@pytest.mark.asyncio
async def test_ac_06_5th_failure_locks_user_via_handler() -> None:
    user = _verified_user(failed=TOTP_LOCKOUT_THRESHOLD)
    users = InMemoryUserRepository()
    users.seed(user)
    uow = FakeUnitOfWork()

    handler = make_lockout_handler(
        uow_factory=lambda: uow,
        users=lambda _s: users,
    )
    await handler(
        TotpVerificationFailed(
            aggregate_id=user.id,
            user_id=user.id,
            failed_attempts=TOTP_LOCKOUT_THRESHOLD,
        )
    )

    persisted = await users.get_by_id(user.id)
    assert persisted is not None
    assert persisted.status is UserStatus.LOCKED
    assert persisted.locked_until is not None
    assert any(isinstance(e, UserLockedDueToTotpFailures) for e in uow.captured_events)


@pytest.mark.asyncio
async def test_ac_06_handler_below_threshold_is_no_op() -> None:
    user = _verified_user(failed=3)
    users = InMemoryUserRepository()
    users.seed(user)
    uow = FakeUnitOfWork()

    handler = make_lockout_handler(
        uow_factory=lambda: uow,
        users=lambda _s: users,
    )
    await handler(TotpVerificationFailed(aggregate_id=user.id, user_id=user.id, failed_attempts=3))

    persisted = await users.get_by_id(user.id)
    assert persisted is not None
    assert persisted.status is UserStatus.VERIFIED
    assert uow.committed is False
    assert uow.captured_events == []


@pytest.mark.asyncio
async def test_ac_06_handler_idempotent_when_already_locked() -> None:
    """Concurrent retries: second invocation observes a locked user and exits cleanly."""
    user = _verified_user(failed=TOTP_LOCKOUT_THRESHOLD)
    users = InMemoryUserRepository()
    users.seed(user)
    uow1 = FakeUnitOfWork()
    handler1 = make_lockout_handler(uow_factory=lambda: uow1, users=lambda _s: users)
    await handler1(
        TotpVerificationFailed(
            aggregate_id=user.id,
            user_id=user.id,
            failed_attempts=TOTP_LOCKOUT_THRESHOLD,
        )
    )
    # Re-fire — should be a no-op
    uow2 = FakeUnitOfWork()
    handler2 = make_lockout_handler(uow_factory=lambda: uow2, users=lambda _s: users)
    await handler2(
        TotpVerificationFailed(
            aggregate_id=user.id,
            user_id=user.id,
            failed_attempts=TOTP_LOCKOUT_THRESHOLD,
        )
    )
    assert uow2.committed is False
    assert uow2.captured_events == []


@pytest.mark.asyncio
async def test_ac_06_handler_user_missing_silently_returns() -> None:
    users = InMemoryUserRepository()  # not seeded
    uow = FakeUnitOfWork()
    handler = make_lockout_handler(uow_factory=lambda: uow, users=lambda _s: users)

    await handler(
        TotpVerificationFailed(
            aggregate_id=uuid4(),
            user_id=uuid4(),
            failed_attempts=TOTP_LOCKOUT_THRESHOLD,
        )
    )
    assert uow.committed is False


@pytest.mark.asyncio
async def test_ac_06_handler_ignores_unrelated_event_types() -> None:
    """Defensive: bus filters by type, but the handler still no-ops on misroute."""
    from vaultchain.identity.domain.events import UserSignedUp

    users = InMemoryUserRepository()
    uow = FakeUnitOfWork()
    handler = make_lockout_handler(uow_factory=lambda: uow, users=lambda _s: users)
    await handler(UserSignedUp(aggregate_id=uuid4(), email="x@y.z"))
    assert uow.committed is False


@pytest.mark.asyncio
async def test_register_lockout_handler_subscribes_to_failure_event() -> None:
    bus = OutboxEventBus()
    users = InMemoryUserRepository()
    uow = FakeUnitOfWork()
    register_lockout_handler(
        bus=bus,
        uow_factory=lambda: uow,
        users=lambda _s: users,
    )
    handlers = bus.handlers_for("identity.totp_verification_failed")
    assert len(handlers) == 1
    assert handlers[0].__qualname__ == "increment_user_lockout_counter"
