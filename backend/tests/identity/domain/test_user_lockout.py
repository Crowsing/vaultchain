"""User aggregate lockout-state tests — AC-phase1-identity-003-06, -07.

Covers the state machine on the User aggregate (no I/O):
- `record_totp_failure` increments counter
- `lock_due_to_totp_failures` flips state on threshold
- `is_locked_now` honours the time window
- `clear_totp_failures` self-heals on successful verify (AC-07)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vaultchain.identity.domain.aggregates import User, UserStatus
from vaultchain.identity.domain.errors import InvalidStateTransition
from vaultchain.identity.domain.events import UserLockedDueToTotpFailures
from vaultchain.identity.domain.value_objects import Email


def _new_verified_user() -> User:
    email = Email("locked@example.com")
    user = User.signup(email=email.value, email_hash=email.hash_blake2b())
    user.pull_events()
    user.status = UserStatus.VERIFIED
    return user


class TestRecordTotpFailure:
    def test_ac_06_record_totp_failure_increments_counter(self) -> None:
        user = _new_verified_user()
        assert user.failed_totp_attempts == 0
        user.record_totp_failure()
        assert user.failed_totp_attempts == 1
        assert user.version == 1

    def test_ac_06_record_below_threshold_does_not_lock(self) -> None:
        user = _new_verified_user()
        for _ in range(4):
            user.record_totp_failure()
        assert user.failed_totp_attempts == 4
        assert user.status is UserStatus.VERIFIED
        assert user.locked_until is None
        assert user.pull_events() == ()  # state-only, no events emitted by this method

    def test_ac_06_record_can_reach_five_without_locking(self) -> None:
        # The handler is what locks; the User state-method is purely the counter.
        user = _new_verified_user()
        for _ in range(5):
            user.record_totp_failure()
        assert user.failed_totp_attempts == 5
        assert user.status is UserStatus.VERIFIED
        assert user.locked_until is None


class TestLockDueToTotpFailures:
    def test_ac_06_5th_failure_locks_user_with_15min_window(self) -> None:
        user = _new_verified_user()
        for _ in range(5):
            user.record_totp_failure()

        anchor = datetime.now(UTC)
        user.lock_due_to_totp_failures(now=anchor)

        assert user.status is UserStatus.LOCKED
        assert user.locked_until == anchor + timedelta(minutes=15)
        events = user.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], UserLockedDueToTotpFailures)
        assert events[0].aggregate_id == user.id

    def test_ac_06_lock_idempotent_when_already_locked(self) -> None:
        user = _new_verified_user()
        for _ in range(5):
            user.record_totp_failure()
        anchor = datetime.now(UTC)
        user.lock_due_to_totp_failures(now=anchor)
        user.pull_events()

        user.lock_due_to_totp_failures(now=anchor + timedelta(minutes=5))

        # Window not extended, no fresh event.
        assert user.locked_until == anchor + timedelta(minutes=15)
        assert user.pull_events() == ()

    def test_ac_06_lock_below_threshold_raises_invalid_state_transition(self) -> None:
        user = _new_verified_user()
        user.record_totp_failure()  # counter=1
        with pytest.raises(InvalidStateTransition):
            user.lock_due_to_totp_failures()


class TestIsLockedNow:
    def test_ac_06_returns_false_when_locked_until_is_none(self) -> None:
        user = _new_verified_user()
        assert user.is_locked_now() is False

    def test_ac_06_returns_true_within_window(self) -> None:
        user = _new_verified_user()
        anchor = datetime.now(UTC)
        user.locked_until = anchor + timedelta(minutes=10)
        assert user.is_locked_now(now=anchor) is True

    def test_ac_07_returns_false_after_window(self) -> None:
        user = _new_verified_user()
        anchor = datetime.now(UTC)
        user.locked_until = anchor - timedelta(seconds=1)
        assert user.is_locked_now(now=anchor) is False


class TestClearTotpFailures:
    def test_ac_07_clear_resets_counter_unlocks_and_restores_verified(self) -> None:
        user = _new_verified_user()
        for _ in range(5):
            user.record_totp_failure()
        anchor = datetime.now(UTC)
        user.lock_due_to_totp_failures(now=anchor)
        user.pull_events()

        user.clear_totp_failures()

        assert user.failed_totp_attempts == 0
        assert user.locked_until is None
        assert user.status is UserStatus.VERIFIED

    def test_ac_07_clear_idempotent_no_change_when_already_clean(self) -> None:
        user = _new_verified_user()
        original_version = user.version
        user.clear_totp_failures()
        assert user.failed_totp_attempts == 0
        assert user.locked_until is None
        # No-op should not bump version.
        assert user.version == original_version

    def test_ac_07_clear_when_unverified_does_not_change_status(self) -> None:
        # An unverified user can also fail TOTP (theoretically before email verify).
        # Clearing should not promote them to VERIFIED.
        user = _new_verified_user()
        user.status = UserStatus.UNVERIFIED
        user.record_totp_failure()
        user.clear_totp_failures()
        assert user.status is UserStatus.UNVERIFIED
