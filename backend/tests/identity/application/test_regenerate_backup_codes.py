"""RegenerateBackupCodes tests — AC-phase1-identity-003-09."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.identity.fakes.fake_backup_code_service import FakeBackupCodeService
from tests.identity.fakes.fake_encryptor import FakeTotpEncryptor
from tests.identity.fakes.fake_repositories import (
    InMemoryTotpSecretRepository,
    InMemoryUserRepository,
)
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.regenerate_backup_codes import (
    BackupCodesRegenerationResult,
    RegenerateBackupCodes,
)
from vaultchain.identity.domain.aggregates import TotpSecret, User, UserStatus
from vaultchain.identity.domain.errors import TotpNotEnrolled
from vaultchain.identity.domain.value_objects import Email


def _verified_user() -> User:
    e = Email("regen@example.com")
    user = User.signup(email=e.value, email_hash=e.hash_blake2b())
    user.pull_events()
    user.status = UserStatus.VERIFIED
    return user


def _wire(
    *, user: User
) -> tuple[
    RegenerateBackupCodes,
    FakeUnitOfWork,
    InMemoryUserRepository,
    InMemoryTotpSecretRepository,
]:
    users = InMemoryUserRepository()
    totps = InMemoryTotpSecretRepository()
    backup_service = FakeBackupCodeService()
    users.seed(user)
    secret = TotpSecret.enroll(
        user_id=user.id,
        secret_plain=b"original-secret",
        backup_codes_hashed=[backup_service.hash(c) for c in backup_service.generate(10)],
        encryptor=FakeTotpEncryptor(),
    )
    totps.seed(secret)
    uow = FakeUnitOfWork()
    use_case = RegenerateBackupCodes(
        uow_factory=lambda: uow,
        users=lambda _s: users,
        totps=lambda _s: totps,
        backup_codes=backup_service,
    )
    return use_case, uow, users, totps


@pytest.mark.asyncio
async def test_ac_09_regenerate_replaces_old_hashes_atomically() -> None:
    user = _verified_user()
    use_case, uow, _users, totps = _wire(user=user)

    secret_before = await totps.get_by_user_id(user.id)
    assert secret_before is not None
    old_hashes = list(secret_before.backup_codes_hashed)

    result = await use_case.execute(user_id=user.id)

    assert isinstance(result, BackupCodesRegenerationResult)
    assert len(result.backup_codes_plaintext) == 10
    secret_after = await totps.get_by_user_id(user.id)
    assert secret_after is not None
    assert len(secret_after.backup_codes_hashed) == 10
    # Old codes are gone (deterministic FakeBackupCodeService re-emits the
    # same generate() output, so we can't assert *value* difference, but
    # we can assert the same UoW commit replaced them in one go).
    assert uow.committed is True
    # Per AC-09: old set fully replaced — assert that ALL hashes correspond
    # to the new plaintext, not any non-listed value.
    expected = {FakeBackupCodeService().hash(c) for c in result.backup_codes_plaintext}
    assert set(secret_after.backup_codes_hashed) == expected
    # Sanity: old hashes shape was identical here, so this is a "replaced
    # in one UoW" check, not a "new vs old" check.
    assert len(old_hashes) == len(secret_after.backup_codes_hashed)


@pytest.mark.asyncio
async def test_ac_09_regenerate_when_no_totp_raises_totp_not_enrolled() -> None:
    user = _verified_user()
    users = InMemoryUserRepository()
    users.seed(user)
    totps = InMemoryTotpSecretRepository()  # empty
    uow = FakeUnitOfWork()
    use_case = RegenerateBackupCodes(
        uow_factory=lambda: uow,
        users=lambda _s: users,
        totps=lambda _s: totps,
        backup_codes=FakeBackupCodeService(),
    )
    with pytest.raises(TotpNotEnrolled):
        await use_case.execute(user_id=user.id)


@pytest.mark.asyncio
async def test_ac_09_regenerate_user_missing_raises_not_found() -> None:
    from vaultchain.shared.domain.errors import NotFoundError

    users = InMemoryUserRepository()
    totps = InMemoryTotpSecretRepository()
    uow = FakeUnitOfWork()
    use_case = RegenerateBackupCodes(
        uow_factory=lambda: uow,
        users=lambda _s: users,
        totps=lambda _s: totps,
        backup_codes=FakeBackupCodeService(),
    )
    with pytest.raises(NotFoundError):
        await use_case.execute(user_id=uuid4())
