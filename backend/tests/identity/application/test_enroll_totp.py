"""EnrollTotp use case tests — AC-phase1-identity-003-02, -03, -10."""

from __future__ import annotations

import pytest

from tests.identity.fakes.fake_backup_code_service import FakeBackupCodeService
from tests.identity.fakes.fake_encryptor import FakeTotpEncryptor
from tests.identity.fakes.fake_repositories import (
    InMemoryTotpSecretRepository,
    InMemoryUserRepository,
)
from tests.identity.fakes.fake_totp_checker import FakeTotpCodeChecker
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.enroll_totp import (
    EnrollTotp,
    TotpEnrollmentResult,
)
from vaultchain.identity.domain.aggregates import User, UserStatus
from vaultchain.identity.domain.errors import TotpAlreadyEnrolled
from vaultchain.identity.domain.events import TotpEnrolled
from vaultchain.identity.domain.value_objects import Email


def _verified_user(email: str = "enroll@example.com") -> User:
    e = Email(email)
    user = User.signup(email=e.value, email_hash=e.hash_blake2b())
    user.pull_events()
    user.status = UserStatus.VERIFIED
    return user


def _wire(
    *,
    user: User | None = None,
    existing_secret: bool = False,
) -> tuple[EnrollTotp, FakeUnitOfWork, InMemoryUserRepository, InMemoryTotpSecretRepository]:
    users = InMemoryUserRepository()
    totps = InMemoryTotpSecretRepository()
    if user is not None:
        users.seed(user)
    if existing_secret and user is not None:
        from vaultchain.identity.domain.aggregates import TotpSecret

        totps.seed(
            TotpSecret.enroll(
                user_id=user.id,
                secret_plain=b"existing",
                backup_codes_hashed=[],
                encryptor=FakeTotpEncryptor(),
            )
        )
    uow = FakeUnitOfWork()
    enrol = EnrollTotp(
        uow_factory=lambda: uow,
        users=lambda _s: users,
        totps=lambda _s: totps,
        encryptor=FakeTotpEncryptor(),
        code_checker=FakeTotpCodeChecker(),
        backup_codes=FakeBackupCodeService(),
    )
    return enrol, uow, users, totps


@pytest.mark.asyncio
async def test_ac_02_enroll_creates_secret_and_backup_codes() -> None:
    user = _verified_user()
    enrol, uow, _users, totps = _wire(user=user)

    result = await enrol.execute(user_id=user.id)

    assert isinstance(result, TotpEnrollmentResult)
    # secret_for_qr is the base32 plaintext (matches the fake's SECRET).
    assert result.secret_for_qr == FakeTotpCodeChecker.SECRET.decode("ascii")
    # 10 backup codes plaintext returned.
    assert len(result.backup_codes_plaintext) == 10
    # Persisted hashes match the fake's deterministic hash format.
    stored = await totps.get_by_user_id(user.id)
    assert stored is not None
    assert len(stored.backup_codes_hashed) == 10
    assert all(h.startswith(FakeBackupCodeService.SENTINEL) for h in stored.backup_codes_hashed)
    # Encrypted secret round-trips back via the encryptor port.
    assert FakeTotpEncryptor().decrypt(stored.secret_encrypted) == FakeTotpCodeChecker.SECRET
    assert uow.committed is True
    assert any(isinstance(e, TotpEnrolled) for e in uow.captured_events)


@pytest.mark.asyncio
async def test_ac_02_plaintext_backup_codes_returned_only_once() -> None:
    """Re-fetching the persisted secret never returns plaintext."""
    user = _verified_user()
    enrol, _uow, _users, totps = _wire(user=user)
    result = await enrol.execute(user_id=user.id)

    stored = await totps.get_by_user_id(user.id)
    assert stored is not None
    # Ensure none of the stored hashes are the plaintext codes.
    plaintext_bytes = {c.encode("ascii") for c in result.backup_codes_plaintext}
    for h in stored.backup_codes_hashed:
        assert h not in plaintext_bytes


@pytest.mark.asyncio
async def test_ac_03_enroll_idempotent_blocked_when_already_enrolled() -> None:
    user = _verified_user()
    enrol, uow, _users, _totps = _wire(user=user, existing_secret=True)

    with pytest.raises(TotpAlreadyEnrolled) as exc:
        await enrol.execute(user_id=user.id)

    assert exc.value.code == "identity.totp_already_enrolled"
    assert exc.value.status_code == 409
    assert uow.committed is False


@pytest.mark.asyncio
async def test_ac_10_qr_payload_uri_uses_otpauth_format() -> None:
    user = _verified_user("alice@example.com")
    enrol, _uow, _users, _totps = _wire(user=user)
    result = await enrol.execute(user_id=user.id)

    uri = result.qr_payload_uri
    assert uri.startswith("otpauth://totp/VaultChain:alice@example.com?")
    assert "secret=" in uri
    assert "issuer=VaultChain" in uri
