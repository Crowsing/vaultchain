"""User aggregate tests — AC-phase1-identity-001-03, -04."""

from __future__ import annotations

import pytest

from vaultchain.identity.domain.aggregates import User, UserStatus
from vaultchain.identity.domain.errors import InvalidStateTransition
from vaultchain.identity.domain.events import UserLocked, UserSignedUp
from vaultchain.identity.domain.value_objects import Email


def _new_user(*, status: UserStatus = UserStatus.UNVERIFIED, version: int = 0) -> User:
    email = Email("alice@example.com")
    user = User.signup(email=email.value, email_hash=email.hash_blake2b())
    # consume the signup event from the buffer so test starts clean.
    user.pull_events()
    user.status = status
    user.version = version
    return user


class TestSignup:
    def test_signup_emits_user_signed_up_event(self) -> None:
        email = Email("new@example.com")
        user = User.signup(email=email.value, email_hash=email.hash_blake2b())
        events = user.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], UserSignedUp)
        assert events[0].email == "new@example.com"
        assert events[0].aggregate_id == user.id

    def test_signup_starts_unverified_with_zero_version(self) -> None:
        email = Email("new@example.com")
        user = User.signup(email=email.value, email_hash=email.hash_blake2b())
        assert user.status is UserStatus.UNVERIFIED
        assert user.version == 0
        assert user.kyc_tier == 0

    def test_pull_events_is_destructive(self) -> None:
        email = Email("new@example.com")
        user = User.signup(email=email.value, email_hash=email.hash_blake2b())
        first = user.pull_events()
        second = user.pull_events()
        assert len(first) == 1
        assert len(second) == 0


class TestVerifyEmail:
    def test_ac_03_unverified_to_verified_increments_version(self) -> None:
        user = _new_user(status=UserStatus.UNVERIFIED, version=3)
        user.verify_email()
        assert user.status is UserStatus.VERIFIED
        assert user.version == 4
        assert user.updated_at is not None

    def test_ac_03_verifying_already_verified_raises_conflict(self) -> None:
        user = _new_user(status=UserStatus.VERIFIED)
        with pytest.raises(InvalidStateTransition) as exc:
            user.verify_email()
        assert exc.value.code == "identity.invalid_state_transition"

    def test_ac_03_verifying_locked_raises_conflict(self) -> None:
        user = _new_user(status=UserStatus.LOCKED)
        with pytest.raises(InvalidStateTransition):
            user.verify_email()


class TestLock:
    def test_ac_04_lock_from_unverified_locks_and_appends_event(self) -> None:
        user = _new_user(status=UserStatus.UNVERIFIED, version=2)
        user.lock(reason="suspicious activity")
        assert user.status is UserStatus.LOCKED
        assert user.version == 3
        events = user.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], UserLocked)
        assert events[0].reason == "suspicious activity"
        assert events[0].aggregate_id == user.id

    def test_ac_04_lock_from_verified_still_locks(self) -> None:
        user = _new_user(status=UserStatus.VERIFIED)
        user.lock(reason="fraud")
        assert user.status is UserStatus.LOCKED

    def test_ac_04_lock_from_locked_remains_locked(self) -> None:
        user = _new_user(status=UserStatus.LOCKED)
        user.lock(reason="repeat")
        assert user.status is UserStatus.LOCKED

    def test_ac_04_lock_with_empty_reason_uses_default(self) -> None:
        user = _new_user()
        user.lock()
        events = user.pull_events()
        assert events[0].reason == ""  # type: ignore[attr-defined]
