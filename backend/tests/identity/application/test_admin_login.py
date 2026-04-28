"""AdminLogin use-case tests — phase1-admin-002a AC-01, AC-02."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.identity.fakes.fake_password_hasher import FakePasswordHasher
from tests.identity.fakes.fake_repositories import InMemoryUserRepository
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.admin_login import AdminLogin
from vaultchain.identity.domain.aggregates import (
    ADMIN_PASSWORD_LOCKOUT_THRESHOLD,
    User,
    UserStatus,
)
from vaultchain.identity.domain.errors import InvalidCredentials, UserLocked
from vaultchain.identity.domain.value_objects import Email

_DEFAULT_TEST_PASSWORD = "correctpassword42!"


def _seed_admin(repo: InMemoryUserRepository, password: str = _DEFAULT_TEST_PASSWORD) -> User:
    hasher = FakePasswordHasher()
    user = User.seed_admin(
        email="admin@example.com",
        email_hash=Email("admin@example.com").hash_blake2b(),
        password_hash=hasher.hash(password),
        full_name="Demo Admin",
        role="admin",
    )
    repo.seed(user)
    return user


def _login(repo: InMemoryUserRepository) -> AdminLogin:
    return AdminLogin(
        uow_factory=lambda: FakeUnitOfWork(),
        users=lambda _s: repo,
        password_hasher=FakePasswordHasher(),
    )


async def test_happy_path_returns_user_id() -> None:
    repo = InMemoryUserRepository()
    admin = _seed_admin(repo)
    res = await _login(repo).execute(email="admin@example.com", password="correctpassword42!")
    assert res.user_id == admin.id


async def test_wrong_password_raises_invalid_credentials() -> None:
    repo = InMemoryUserRepository()
    _seed_admin(repo)
    with pytest.raises(InvalidCredentials):
        await _login(repo).execute(email="admin@example.com", password="wrong-password-1!")


async def test_unknown_email_raises_invalid_credentials() -> None:
    repo = InMemoryUserRepository()
    with pytest.raises(InvalidCredentials):
        await _login(repo).execute(email="nope@example.com", password="anything-good-12!")


async def test_user_actor_cannot_login_as_admin() -> None:
    repo = InMemoryUserRepository()
    user = User.signup(email="user@example.com", email_hash=b"\x00" * 32)
    user.password_hash = FakePasswordHasher().hash("correctpassword42!")
    repo.seed(user)
    with pytest.raises(InvalidCredentials):
        await _login(repo).execute(email="user@example.com", password="correctpassword42!")


async def test_locked_admin_rejected_with_user_locked() -> None:
    repo = InMemoryUserRepository()
    admin = _seed_admin(repo)
    admin.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    admin.status = UserStatus.LOCKED
    admin.version += 1
    repo._by_id[admin.id] = admin
    with pytest.raises(UserLocked):
        await _login(repo).execute(email="admin@example.com", password="correctpassword42!")


async def test_threshold_failures_lock_account() -> None:
    repo = InMemoryUserRepository()
    _seed_admin(repo)
    login = _login(repo)
    for _ in range(ADMIN_PASSWORD_LOCKOUT_THRESHOLD):
        with pytest.raises(InvalidCredentials):
            await login.execute(email="admin@example.com", password="bad-password-12!")

    # The next attempt — even with the right password — must hit the lockout.
    with pytest.raises(UserLocked):
        await login.execute(email="admin@example.com", password="correctpassword42!")


async def test_successful_login_resets_failure_counter() -> None:
    repo = InMemoryUserRepository()
    admin = _seed_admin(repo)
    login = _login(repo)

    with pytest.raises(InvalidCredentials):
        await login.execute(email="admin@example.com", password="bad-password-12!")
    await login.execute(email="admin@example.com", password="correctpassword42!")

    fresh = await repo.get_by_id(admin.id)
    assert fresh is not None
    assert fresh.login_failure_count == 0


async def test_self_healing_clears_after_window() -> None:
    repo = InMemoryUserRepository()
    admin = _seed_admin(repo)
    admin.locked_until = datetime.now(UTC) - timedelta(minutes=1)  # past window
    admin.login_failure_count = ADMIN_PASSWORD_LOCKOUT_THRESHOLD
    admin.status = UserStatus.LOCKED
    admin.version += 1
    repo._by_id[admin.id] = admin

    res = await _login(repo).execute(email="admin@example.com", password="correctpassword42!")
    assert res.user_id == admin.id
    fresh = await repo.get_by_id(admin.id)
    assert fresh is not None
    assert fresh.locked_until is None
    assert fresh.status is UserStatus.VERIFIED
    assert fresh.login_failure_count == 0
