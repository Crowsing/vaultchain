"""AdminTotpVerify use-case tests — phase1-admin-002a AC-03, AC-07."""

from __future__ import annotations

import pytest

from tests.identity.fakes.fake_access_token_cache import FakeAccessTokenCache
from tests.identity.fakes.fake_backup_code_service import FakeBackupCodeService
from tests.identity.fakes.fake_encryptor import FakeTotpEncryptor
from tests.identity.fakes.fake_repositories import (
    InMemorySessionRepository,
    InMemoryTotpSecretRepository,
    InMemoryUserRepository,
)
from tests.identity.fakes.fake_token_generator import DeterministicTokenGenerator
from tests.identity.fakes.fake_totp_checker import FakeTotpCodeChecker
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.admin_totp_verify import (
    ADMIN_SCOPES,
    AdminTotpVerify,
)
from vaultchain.identity.application.create_session import CreateSession
from vaultchain.identity.application.verify_totp import VerifyTotp
from vaultchain.identity.domain.aggregates import TotpSecret, User
from vaultchain.identity.domain.errors import InvalidCredentials
from vaultchain.identity.domain.events import (
    AdminAuthenticated,
    UserAuthenticated,
)
from vaultchain.identity.domain.value_objects import Email


def _wire_admin_totp_verify(
    *,
    users: InMemoryUserRepository,
    sessions: InMemorySessionRepository,
    totps: InMemoryTotpSecretRepository,
    cache: FakeAccessTokenCache,
    captured_events: list,
) -> AdminTotpVerify:
    encryptor = FakeTotpEncryptor()
    code_checker = FakeTotpCodeChecker(accepted_codes=("123456",))
    backup_codes = FakeBackupCodeService()
    token_gen = DeterministicTokenGenerator()

    def _uow_factory() -> FakeUnitOfWork:
        u = FakeUnitOfWork()
        captured_events.append(u)
        return u

    verify_totp = VerifyTotp(
        uow_factory=_uow_factory,
        users=lambda _s: users,
        totps=lambda _s: totps,
        encryptor=encryptor,
        code_checker=code_checker,
        backup_codes=backup_codes,
    )
    create_session = CreateSession(
        uow_factory=_uow_factory,
        sessions=lambda _s: sessions,
        cache=cache,
        token_gen=token_gen,
    )
    return AdminTotpVerify(
        uow_factory=_uow_factory,
        users=lambda _s: users,
        verify_totp=verify_totp,
        create_session=create_session,
    )


def _seed_admin_with_totp(
    users: InMemoryUserRepository, totps: InMemoryTotpSecretRepository
) -> User:
    admin = User.seed_admin(
        email="admin@example.com",
        email_hash=Email("admin@example.com").hash_blake2b(),
        password_hash="$2b$12$" + "x" * 53,
        full_name="Demo Admin",
        role="admin",
    )
    users.seed(admin)
    encryptor = FakeTotpEncryptor()
    secret = TotpSecret.enroll(
        user_id=admin.id,
        secret_plain=b"JBSWY3DPEHPK3PXP",
        backup_codes_hashed=[],
        encryptor=encryptor,
    )
    totps.seed(secret)
    return admin


async def test_happy_path_creates_admin_session() -> None:
    users = InMemoryUserRepository()
    sessions = InMemorySessionRepository()
    totps = InMemoryTotpSecretRepository()
    cache = FakeAccessTokenCache()
    captured_uows: list[FakeUnitOfWork] = []

    use_case = _wire_admin_totp_verify(
        users=users,
        sessions=sessions,
        totps=totps,
        cache=cache,
        captured_events=captured_uows,
    )
    admin = _seed_admin_with_totp(users, totps)

    res = await use_case.execute(user_id=admin.id, code="123456", ip="1.2.3.4", user_agent="ua")
    assert res.user_id == admin.id
    assert res.email == admin.email
    assert res.role == "admin"
    assert res.full_name == "Demo Admin"
    assert res.session.access_token_raw
    assert res.session.refresh_token_raw

    cached_payloads = [p for p in cache._store.values() if p.user_id == admin.id]
    assert cached_payloads, "expected an admin session entry in the cache"
    assert cached_payloads[0].scopes == ADMIN_SCOPES

    captured_event_types = [
        type(e).__name__ for u in captured_uows for e in u.captured_events if u.committed
    ]
    assert AdminAuthenticated.__name__ in captured_event_types
    assert UserAuthenticated.__name__ in captured_event_types


async def test_wrong_code_raises_invalid_credentials() -> None:
    users = InMemoryUserRepository()
    sessions = InMemorySessionRepository()
    totps = InMemoryTotpSecretRepository()
    cache = FakeAccessTokenCache()
    captured: list[FakeUnitOfWork] = []
    use_case = _wire_admin_totp_verify(
        users=users, sessions=sessions, totps=totps, cache=cache, captured_events=captured
    )
    admin = _seed_admin_with_totp(users, totps)

    with pytest.raises(InvalidCredentials):
        await use_case.execute(user_id=admin.id, code="999999")


async def test_non_admin_user_rejected() -> None:
    users = InMemoryUserRepository()
    sessions = InMemorySessionRepository()
    totps = InMemoryTotpSecretRepository()
    cache = FakeAccessTokenCache()
    captured: list[FakeUnitOfWork] = []
    use_case = _wire_admin_totp_verify(
        users=users, sessions=sessions, totps=totps, cache=cache, captured_events=captured
    )

    user = User.signup(email="u@example.com", email_hash=b"\x00" * 32)
    users.seed(user)
    encryptor = FakeTotpEncryptor()
    totps.seed(
        TotpSecret.enroll(
            user_id=user.id,
            secret_plain=b"JBSWY3DPEHPK3PXP",
            backup_codes_hashed=[],
            encryptor=encryptor,
        )
    )

    with pytest.raises(InvalidCredentials):
        await use_case.execute(user_id=user.id, code="123456")
