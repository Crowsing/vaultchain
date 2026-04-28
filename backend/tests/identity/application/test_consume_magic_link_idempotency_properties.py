"""Hypothesis property tests — `MagicLinkConsumed` re-delivery idempotency.

The brief calls out this property: "for any sequence of redeliveries
of MagicLinkConsumed for the same magic link, the user is verified at
most once and version is incremented at most once".

This is the lightweight in-handler defence — production also has the
`event_handler_log` UNIQUE constraint at the storage layer, but the
handler must hold up on its own when driven outside the outbox (tests,
in-process pumps, future direct callers).
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
from vaultchain.identity.domain.events import MagicLinkConsumed
from vaultchain.identity.domain.value_objects import Email

pytestmark = pytest.mark.property


@given(redeliveries=st.integers(min_value=1, max_value=12))
@settings(max_examples=30, deadline=None)
def test_redelivery_keeps_version_incremented_at_most_once(redeliveries: int) -> None:
    """N firings of the same MagicLinkConsumed event ⇒ version ↑ exactly once."""

    async def run() -> None:
        users = InMemoryUserRepository()
        e = Email(f"u-{uuid4().hex[:8]}@x.io")
        user = User.signup(email=e.value, email_hash=e.hash_blake2b())
        user.pull_events()
        users.seed(user)
        version_before = user.version

        handler = make_signup_verification_handler(
            uow_factory=lambda: FakeUnitOfWork(),
            users=lambda _s: users,
        )
        event = MagicLinkConsumed(aggregate_id=user.id, user_id=user.id, mode=MagicLinkMode.SIGNUP)

        for _ in range(redeliveries):
            await handler(event)

        final = await users.get_by_id(user.id)
        assert final is not None
        assert final.status is UserStatus.VERIFIED
        # Version moved exactly +1 — verify_email() succeeded once, then
        # subsequent firings caught InvalidStateTransition.
        assert final.version == version_before + 1

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


@given(redeliveries=st.integers(min_value=1, max_value=12))
@settings(max_examples=20, deadline=None)
def test_login_mode_redelivery_never_changes_user(redeliveries: int) -> None:
    """Login-mode consume must never change user status, even with N firings."""

    async def run() -> None:
        users = InMemoryUserRepository()
        e = Email(f"v-{uuid4().hex[:8]}@x.io")
        user = User.signup(email=e.value, email_hash=e.hash_blake2b())
        user.pull_events()
        user.verify_email()  # verified before login flow
        users.seed(user)
        version_before = user.version
        status_before = user.status

        handler = make_signup_verification_handler(
            uow_factory=lambda: FakeUnitOfWork(),
            users=lambda _s: users,
        )
        event = MagicLinkConsumed(aggregate_id=user.id, user_id=user.id, mode=MagicLinkMode.LOGIN)

        for _ in range(redeliveries):
            await handler(event)

        final = await users.get_by_id(user.id)
        assert final is not None
        assert final.version == version_before
        assert final.status is status_before
