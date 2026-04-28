"""VerifyTotp use case tests — AC-phase1-identity-003-04, -05, -07, -08."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.identity.fakes.fake_backup_code_service import FakeBackupCodeService
from tests.identity.fakes.fake_encryptor import FakeTotpEncryptor
from tests.identity.fakes.fake_repositories import (
    InMemoryTotpSecretRepository,
    InMemoryUserRepository,
)
from tests.identity.fakes.fake_totp_checker import FakeTotpCodeChecker
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.verify_totp import (
    TotpVerifyResult,
    VerifyTotp,
)
from vaultchain.identity.domain.aggregates import (
    TOTP_LOCKOUT_THRESHOLD,
    TotpSecret,
    User,
    UserStatus,
)
from vaultchain.identity.domain.errors import TotpNotEnrolled, UserLocked
from vaultchain.identity.domain.events import (
    TotpVerificationFailed,
    TotpVerified,
)
from vaultchain.identity.domain.value_objects import Email


def _verified_user(*, email: str = "verify@example.com", failed: int = 0) -> User:
    e = Email(email)
    user = User.signup(email=e.value, email_hash=e.hash_blake2b())
    user.pull_events()
    user.status = UserStatus.VERIFIED
    user.failed_totp_attempts = failed
    return user


def _wire(
    *,
    user: User,
    accepted_codes: tuple[str, ...] = ("123456",),
) -> tuple[VerifyTotp, FakeUnitOfWork, InMemoryUserRepository, InMemoryTotpSecretRepository]:
    users = InMemoryUserRepository()
    totps = InMemoryTotpSecretRepository()
    users.seed(user)
    encryptor = FakeTotpEncryptor()
    backup_service = FakeBackupCodeService()
    secret = TotpSecret.enroll(
        user_id=user.id,
        secret_plain=FakeTotpCodeChecker.SECRET,
        backup_codes_hashed=[backup_service.hash(c) for c in backup_service.generate(10)],
        encryptor=encryptor,
    )
    totps.seed(secret)
    uow = FakeUnitOfWork()
    verify = VerifyTotp(
        uow_factory=lambda: uow,
        users=lambda _s: users,
        totps=lambda _s: totps,
        encryptor=encryptor,
        code_checker=FakeTotpCodeChecker(accepted_codes=accepted_codes),
        backup_codes=backup_service,
    )
    return verify, uow, users, totps


@pytest.mark.asyncio
async def test_ac_04_verify_success_resets_counter_and_emits_verified() -> None:
    user = _verified_user(failed=2)
    verify, uow, users, totps = _wire(user=user)

    result = await verify.execute(user_id=user.id, code="123456")

    assert result == TotpVerifyResult(success=True, attempts_remaining=None)
    persisted = await users.get_by_id(user.id)
    assert persisted is not None
    assert persisted.failed_totp_attempts == 0
    secret = await totps.get_by_user_id(user.id)
    assert secret is not None
    assert secret.last_verified_at is not None
    assert any(isinstance(e, TotpVerified) for e in uow.captured_events)


@pytest.mark.asyncio
async def test_ac_05_verify_wrong_code_returns_attempts_remaining_4() -> None:
    user = _verified_user(failed=0)
    verify, uow, users, _totps = _wire(user=user)

    result = await verify.execute(user_id=user.id, code="000000")

    assert result == TotpVerifyResult(success=False, attempts_remaining=4)
    persisted = await users.get_by_id(user.id)
    assert persisted is not None
    assert persisted.failed_totp_attempts == 1
    failed_events = [e for e in uow.captured_events if isinstance(e, TotpVerificationFailed)]
    assert len(failed_events) == 1
    assert failed_events[0].failed_attempts == 1


@pytest.mark.asyncio
async def test_ac_05_verify_does_not_raise_on_wrong_code() -> None:
    user = _verified_user()
    verify, _uow, _users, _totps = _wire(user=user)

    # Just confirm no exception leaks; the brief is explicit on this.
    result = await verify.execute(user_id=user.id, code="bad")
    assert result.success is False


@pytest.mark.asyncio
async def test_ac_05_attempts_remaining_clamped_to_zero_after_threshold() -> None:
    user = _verified_user(failed=TOTP_LOCKOUT_THRESHOLD)  # already at limit
    verify, _uow, _users, _totps = _wire(user=user)

    result = await verify.execute(user_id=user.id, code="bad")
    assert result.success is False
    assert result.attempts_remaining == 0


@pytest.mark.asyncio
async def test_ac_06_locked_user_during_window_raises_user_locked() -> None:
    user = _verified_user(failed=TOTP_LOCKOUT_THRESHOLD)
    user.status = UserStatus.LOCKED
    user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    verify, _uow, _users, _totps = _wire(user=user)

    with pytest.raises(UserLocked) as exc:
        await verify.execute(user_id=user.id, code="123456")
    assert exc.value.code == "identity.user_locked"
    assert exc.value.status_code == 403
    assert "locked_until" in exc.value.details


@pytest.mark.asyncio
async def test_ac_07_locked_user_self_heals_after_window() -> None:
    user = _verified_user(failed=TOTP_LOCKOUT_THRESHOLD)
    user.status = UserStatus.LOCKED
    user.locked_until = datetime.now(UTC) - timedelta(seconds=1)  # expired
    verify, _uow, users, _totps = _wire(user=user)

    result = await verify.execute(user_id=user.id, code="123456")
    assert result.success is True
    persisted = await users.get_by_id(user.id)
    assert persisted is not None
    assert persisted.status is UserStatus.VERIFIED
    assert persisted.failed_totp_attempts == 0
    assert persisted.locked_until is None


@pytest.mark.asyncio
async def test_ac_08_verify_with_backup_code_consumes_code_and_succeeds() -> None:
    user = _verified_user()
    verify, _uow, _users, totps = _wire(user=user)
    # A known code from FakeBackupCodeService.generate output.
    valid_code = FakeBackupCodeService().generate(10)[0]

    result = await verify.execute(user_id=user.id, code=valid_code, use_backup_code=True)
    assert result.success is True

    secret = await totps.get_by_user_id(user.id)
    assert secret is not None
    # One-time use: hash for that code is gone from the stored list.
    assert FakeBackupCodeService().hash(valid_code) not in secret.backup_codes_hashed
    assert len(secret.backup_codes_hashed) == 9


@pytest.mark.asyncio
async def test_ac_08_backup_code_failure_does_not_consume_failure_counter() -> None:
    user = _verified_user(failed=2)
    verify, uow, users, _totps = _wire(user=user)

    result = await verify.execute(user_id=user.id, code="WRONG-CODE", use_backup_code=True)
    assert result.success is False
    persisted = await users.get_by_id(user.id)
    assert persisted is not None
    assert persisted.failed_totp_attempts == 2  # unchanged
    assert not any(isinstance(e, TotpVerificationFailed) for e in uow.captured_events)


@pytest.mark.asyncio
async def test_verify_when_no_totp_enrolled_raises_totp_not_enrolled() -> None:
    user = _verified_user()
    users = InMemoryUserRepository()
    users.seed(user)
    totps = InMemoryTotpSecretRepository()
    uow = FakeUnitOfWork()
    verify = VerifyTotp(
        uow_factory=lambda: uow,
        users=lambda _s: users,
        totps=lambda _s: totps,
        encryptor=FakeTotpEncryptor(),
        code_checker=FakeTotpCodeChecker(accepted_codes=("123456",)),
        backup_codes=FakeBackupCodeService(),
    )
    with pytest.raises(TotpNotEnrolled):
        await verify.execute(user_id=user.id, code="123456")


@pytest.mark.asyncio
async def test_verify_when_user_missing_raises_not_found() -> None:
    from vaultchain.shared.domain.errors import NotFoundError

    users = InMemoryUserRepository()  # not seeded
    totps = InMemoryTotpSecretRepository()
    uow = FakeUnitOfWork()
    verify = VerifyTotp(
        uow_factory=lambda: uow,
        users=lambda _s: users,
        totps=lambda _s: totps,
        encryptor=FakeTotpEncryptor(),
        code_checker=FakeTotpCodeChecker(accepted_codes=("123456",)),
        backup_codes=FakeBackupCodeService(),
    )
    with pytest.raises(NotFoundError):
        await verify.execute(user_id=uuid4(), code="123456")
