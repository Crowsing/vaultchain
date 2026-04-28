"""Signup-mode verification handler tests — AC-phase1-identity-002-09."""

from __future__ import annotations

from uuid import UUID

import pytest

from tests.identity.fakes.fake_repositories import InMemoryUserRepository
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.signup_verification_handler import (
    make_signup_verification_handler,
)
from vaultchain.identity.domain.aggregates import (
    MagicLinkMode,
    User,
    UserStatus,
)
from vaultchain.identity.domain.events import (
    MagicLinkConsumed,
    UserSignedUp,
)
from vaultchain.identity.domain.value_objects import Email


def _new_user(email: str = "u@x.io") -> User:
    e = Email(email)
    return User.signup(email=e.value, email_hash=e.hash_blake2b())


@pytest.mark.asyncio
async def test_ac_09_signup_consume_handler_transitions_user_to_verified() -> None:
    users = InMemoryUserRepository()
    user = _new_user()
    user.pull_events()  # drop the UserSignedUp event so version stays clean
    users.seed(user)
    captured_uow = FakeUnitOfWork()

    handler = make_signup_verification_handler(
        uow_factory=lambda: captured_uow,
        users=lambda _s: users,
    )

    event = MagicLinkConsumed(
        aggregate_id=user.id,
        user_id=user.id,
        mode=MagicLinkMode.SIGNUP,
    )
    await handler(event)

    persisted = await users.get_by_id(user.id)
    assert persisted is not None
    assert persisted.status is UserStatus.VERIFIED
    assert persisted.version == user.version + 1


@pytest.mark.asyncio
async def test_ac_09_signup_consume_handler_idempotent_on_redelivery() -> None:
    """If invoked twice for the same event, the user transitions only once.

    Real outbox idempotency lives in `event_handler_log` (UNIQUE on
    `(event_id, handler_name)`); this test asserts the in-handler
    behaviour: re-firing must not bump version or violate the state
    machine.
    """
    users = InMemoryUserRepository()
    user = _new_user()
    user.pull_events()
    users.seed(user)
    handler = make_signup_verification_handler(
        uow_factory=lambda: FakeUnitOfWork(), users=lambda _s: users
    )

    event = MagicLinkConsumed(aggregate_id=user.id, user_id=user.id, mode=MagicLinkMode.SIGNUP)

    await handler(event)
    after_first = await users.get_by_id(user.id)
    assert after_first is not None
    version_after_first = after_first.version

    await handler(event)
    await handler(event)
    final = await users.get_by_id(user.id)
    assert final is not None
    # Version did not move because the user was already verified.
    assert final.version == version_after_first
    assert final.status is UserStatus.VERIFIED


@pytest.mark.asyncio
async def test_ac_09_login_mode_does_not_transition_user() -> None:
    """In login mode (existing verified user), the handler must be a no-op."""
    users = InMemoryUserRepository()
    user = _new_user()
    user.pull_events()
    user.verify_email()
    users.seed(user)
    handler = make_signup_verification_handler(
        uow_factory=lambda: FakeUnitOfWork(), users=lambda _s: users
    )

    event = MagicLinkConsumed(aggregate_id=user.id, user_id=user.id, mode=MagicLinkMode.LOGIN)
    await handler(event)

    persisted = await users.get_by_id(user.id)
    assert persisted is not None
    assert persisted.status is UserStatus.VERIFIED
    assert persisted.version == user.version  # unchanged


@pytest.mark.asyncio
async def test_ac_09_handler_no_ops_when_user_missing() -> None:
    users = InMemoryUserRepository()
    handler = make_signup_verification_handler(
        uow_factory=lambda: FakeUnitOfWork(), users=lambda _s: users
    )

    event = MagicLinkConsumed(
        aggregate_id=user_id_dummy(),
        user_id=user_id_dummy(),
        mode=MagicLinkMode.SIGNUP,
    )
    # Should NOT raise — user gone is treated as a missed-but-recoverable event.
    await handler(event)


def user_id_dummy() -> UUID:
    """Stable dummy uuid for missing-user test."""
    return UUID("00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
async def test_ac_09_handler_filters_unrelated_events() -> None:
    """Handler must defensively ignore events not of type MagicLinkConsumed."""
    users = InMemoryUserRepository()
    user = _new_user()
    user.pull_events()
    users.seed(user)
    handler = make_signup_verification_handler(
        uow_factory=lambda: FakeUnitOfWork(), users=lambda _s: users
    )

    # Fire a different event type — handler should be a no-op.
    other = UserSignedUp(aggregate_id=user.id, email=user.email)
    await handler(other)  # type: ignore[arg-type]

    persisted = await users.get_by_id(user.id)
    assert persisted is not None
    assert persisted.status is UserStatus.UNVERIFIED  # untouched
