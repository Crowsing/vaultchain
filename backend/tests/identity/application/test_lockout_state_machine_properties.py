"""Hypothesis property tests for the TOTP lockout state machine.

Drives long random sequences of (success, failure) attempts through the
User aggregate's state methods (and a synchronous handler simulation)
and asserts the user stays in the legal state graph at every step.

These are pure-domain property tests (no I/O) — the use case wiring is
covered by the example tests in test_verify_totp.py and the handler
tests in test_lockout_handler.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vaultchain.identity.domain.aggregates import (
    TOTP_LOCKOUT_THRESHOLD,
    TOTP_LOCKOUT_WINDOW,
    User,
    UserStatus,
)
from vaultchain.identity.domain.value_objects import Email

pytestmark = pytest.mark.property


def _new_verified_user() -> User:
    e = Email("prop@example.com")
    user = User.signup(email=e.value, email_hash=e.hash_blake2b())
    user.pull_events()
    user.status = UserStatus.VERIFIED
    return user


def _apply_step(user: User, *, success: bool) -> None:
    """Mirror the production sequence: use case mutates first, then the
    asynchronous handler decides the lockout transition.
    """
    if success:
        user.clear_totp_failures()
        return

    if user.is_locked_now():
        # During lockout, the use case raises and never increments — model that.
        return

    user.record_totp_failure()
    # Handler runs after the use case; threshold-or-above triggers the lock.
    if user.failed_totp_attempts >= TOTP_LOCKOUT_THRESHOLD and not user.is_locked_now():
        user.lock_due_to_totp_failures()
        user.pull_events()  # discard for the test — observability only


@given(steps=st.lists(st.booleans(), min_size=1, max_size=30))
@settings(max_examples=80, deadline=None)
def test_user_state_stays_in_legal_graph(steps: list[bool]) -> None:
    """At every step: status ∈ {verified, locked}; locked → locked_until set."""
    user = _new_verified_user()
    for ok in steps:
        _apply_step(user, success=ok)
        assert user.status in (UserStatus.VERIFIED, UserStatus.LOCKED)
        if user.status is UserStatus.LOCKED:
            assert user.locked_until is not None
        else:
            # In the verified branch the counter must always be sub-threshold.
            assert user.failed_totp_attempts < TOTP_LOCKOUT_THRESHOLD


@given(failures_below=st.integers(min_value=0, max_value=TOTP_LOCKOUT_THRESHOLD - 1))
@settings(max_examples=20, deadline=None)
def test_below_threshold_keeps_user_verified(failures_below: int) -> None:
    """K<threshold failures → counter==K, status==verified, no lockout."""
    user = _new_verified_user()
    for _ in range(failures_below):
        _apply_step(user, success=False)
    assert user.failed_totp_attempts == failures_below
    assert user.status is UserStatus.VERIFIED
    assert user.locked_until is None


@given(failures=st.integers(min_value=TOTP_LOCKOUT_THRESHOLD, max_value=10))
@settings(max_examples=10, deadline=None)
def test_threshold_or_more_failures_locks_user(failures: int) -> None:
    """K>=threshold → status==locked, locked_until set."""
    user = _new_verified_user()
    for _ in range(failures):
        _apply_step(user, success=False)
    assert user.status is UserStatus.LOCKED
    assert user.locked_until is not None


@given(window_offset=st.integers(min_value=1, max_value=86400))
@settings(max_examples=15, deadline=None)
def test_self_heal_after_window_resets_counter_and_unlocks(window_offset: int) -> None:
    """If the lockout window has elapsed, a successful step clears the lockout."""
    user = _new_verified_user()
    # Fast-forward to a locked state with locked_until in the past.
    for _ in range(TOTP_LOCKOUT_THRESHOLD):
        _apply_step(user, success=False)
    assert user.status is UserStatus.LOCKED
    user.locked_until = datetime.now(UTC) - timedelta(seconds=window_offset)

    _apply_step(user, success=True)

    assert user.status is UserStatus.VERIFIED
    assert user.failed_totp_attempts == 0
    assert user.locked_until is None


@given(failures=st.integers(min_value=TOTP_LOCKOUT_THRESHOLD, max_value=10))
@settings(max_examples=8, deadline=None)
def test_lockout_window_is_15_minutes_from_first_lock(failures: int) -> None:
    user = _new_verified_user()
    before = datetime.now(UTC)
    for _ in range(failures):
        _apply_step(user, success=False)
    after = datetime.now(UTC)
    assert user.locked_until is not None
    # locked_until should be in the [before+window, after+window] interval.
    assert before + TOTP_LOCKOUT_WINDOW <= user.locked_until <= after + TOTP_LOCKOUT_WINDOW
