"""User-aggregate admin extensions — phase1-admin-002a AC-02, AC-06."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from vaultchain.identity.domain.aggregates import (
    ADMIN_PASSWORD_LOCKOUT_THRESHOLD,
    User,
    UserStatus,
)
from vaultchain.identity.domain.errors import InvalidStateTransition
from vaultchain.identity.domain.value_objects import ActorType


def _admin() -> User:
    return User.seed_admin(
        email="admin@example.com",
        email_hash=b"\x01" * 32,
        password_hash="$2b$12$" + "x" * 53,
        full_name="Demo Admin",
        role="admin",
    )


def test_seed_admin_sets_admin_actor_type() -> None:
    u = _admin()
    assert u.actor_type is ActorType.ADMIN
    assert u.is_admin() is True
    assert u.status is UserStatus.VERIFIED
    assert u.password_hash is not None
    assert u.metadata.get("full_name") == "Demo Admin"
    assert u.metadata.get("admin_role") == "admin"


def test_record_password_failure_increments_counter() -> None:
    u = _admin()
    u.record_password_failure()
    assert u.login_failure_count == 1
    assert u.version == 1


def test_lock_due_to_password_failures_requires_threshold() -> None:
    u = _admin()
    with pytest.raises(InvalidStateTransition):
        u.lock_due_to_password_failures()


def test_lock_due_to_password_failures_locks_after_threshold() -> None:
    u = _admin()
    for _ in range(ADMIN_PASSWORD_LOCKOUT_THRESHOLD):
        u.record_password_failure()

    now = datetime.now(UTC)
    u.lock_due_to_password_failures(now=now)

    assert u.status is UserStatus.LOCKED
    assert u.locked_until is not None
    assert u.locked_until > now
    assert u.locked_until == now + timedelta(minutes=30)


def test_clear_password_failures_resets_counter() -> None:
    u = _admin()
    u.record_password_failure()
    u.clear_password_failures()
    assert u.login_failure_count == 0


def test_clear_password_failures_no_op_when_zero() -> None:
    u = _admin()
    pre = u.version
    u.clear_password_failures()
    assert u.version == pre


def test_user_signup_default_actor_is_user() -> None:
    u = User.signup(email="a@b.io", email_hash=b"\x00" * 32, user_id=uuid4())
    assert u.actor_type is ActorType.USER
    assert u.is_admin() is False
