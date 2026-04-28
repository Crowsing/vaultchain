"""Identity repository adapter tests — AC-phase1-identity-001-08, -09.

Real Postgres via testcontainers. Tests exercise the round-trip add/get plus
optimistic-lock semantics on `users`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from vaultchain.identity.domain.aggregates import (
    MagicLink,
    Session,
    TotpSecret,
    User,
    UserStatus,
)
from vaultchain.identity.infra.repositories import (
    SqlAlchemyMagicLinkRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyTotpSecretRepository,
    SqlAlchemyUserRepository,
)
from vaultchain.shared.domain.errors import StaleAggregate
from vaultchain.shared.infra.unit_of_work import SqlAlchemyUnitOfWork

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _alembic_config(async_dsn: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", async_dsn)
    return cfg


@pytest.fixture(scope="module")
def pg_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="module")
def async_dsn(pg_container: PostgresContainer) -> str:
    raw = pg_container.get_connection_url()
    return raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest_asyncio.fixture
async def migrated_engine(async_dsn: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[object]:
    monkeypatch.setenv("DATABASE_URL", async_dsn)
    cfg = _alembic_config(async_dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_async_engine(async_dsn, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()
        await asyncio.to_thread(command.downgrade, cfg, "base")


def _new_user(email: str = "round@example.com") -> User:
    user = User.signup(email=email, email_hash=b"\x00" * 32)
    user.pull_events()
    return user


def _make_session(user_id: object, *, expires_in_days: int = 30) -> Session:
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        user_id=user_id,  # type: ignore[arg-type]
        refresh_token_hash=b"refresh-" + uuid4().bytes,
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=expires_in_days),
    )


@pytest.mark.asyncio
async def test_user_add_and_get_by_id_round_trip(migrated_engine: object) -> None:
    factory = async_sessionmaker(migrated_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]
    uow = SqlAlchemyUnitOfWork(factory)
    user = _new_user("rt@example.com")
    async with uow:
        repo = SqlAlchemyUserRepository(uow.session)
        await repo.add(user)
        await uow.commit()

    async with uow:
        repo = SqlAlchemyUserRepository(uow.session)
        loaded = await repo.get_by_id(user.id)
    assert loaded is not None
    assert loaded.email == "rt@example.com"
    assert loaded.status is UserStatus.UNVERIFIED


@pytest.mark.asyncio
async def test_ac_08_get_by_email_normalises_input(migrated_engine: object) -> None:
    factory = async_sessionmaker(migrated_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]
    uow = SqlAlchemyUnitOfWork(factory)
    user = _new_user("normed@example.com")
    async with uow:
        repo = SqlAlchemyUserRepository(uow.session)
        await repo.add(user)
        await uow.commit()

    async with uow:
        repo = SqlAlchemyUserRepository(uow.session)
        for variant in (
            "normed@example.com",
            "  normed@example.com  ",
            "NORMED@example.com",
            "  Normed@Example.COM ",
        ):
            loaded = await repo.get_by_email(variant)
            assert loaded is not None, f"variant {variant!r} did not resolve"
            assert loaded.id == user.id


@pytest.mark.asyncio
async def test_user_get_by_id_returns_none_for_missing(migrated_engine: object) -> None:
    factory = async_sessionmaker(migrated_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]
    uow = SqlAlchemyUnitOfWork(factory)
    async with uow:
        repo = SqlAlchemyUserRepository(uow.session)
        loaded = await repo.get_by_id(uuid4())
    assert loaded is None


@pytest.mark.asyncio
async def test_ac_09_optimistic_lock_concurrent_user_update_raises_stale(
    migrated_engine: object,
) -> None:
    factory = async_sessionmaker(migrated_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]
    user = _new_user("oplock@example.com")
    setup_uow = SqlAlchemyUnitOfWork(factory)
    async with setup_uow:
        await SqlAlchemyUserRepository(setup_uow.session).add(user)
        await setup_uow.commit()

    # Pre-load two independent copies BEFORE any commit happens, so both
    # writers observe version=0. Otherwise, the second SELECT would see the
    # already-committed state and raise a domain error instead of StaleAggregate.
    async def load() -> User:
        uow = SqlAlchemyUnitOfWork(factory)
        async with uow:
            loaded = await SqlAlchemyUserRepository(uow.session).get_by_id(user.id)
            assert loaded is not None
            return loaded

    user_a = await load()
    user_b = await load()
    user_a.verify_email()
    user_b.lock(reason="parallel writer")
    user_b.pull_events()  # discard so commit doesn't try to write events

    async def commit_via_repo(updated: User) -> bool:
        uow = SqlAlchemyUnitOfWork(factory)
        async with uow:
            await SqlAlchemyUserRepository(uow.session).update(updated)
            await uow.commit()
            return True

    a, b = await asyncio.gather(
        commit_via_repo(user_a),
        commit_via_repo(user_b),
        return_exceptions=True,
    )
    successes = [r for r in (a, b) if r is True]
    failures = [r for r in (a, b) if isinstance(r, StaleAggregate)]
    assert len(successes) == 1
    assert len(failures) == 1


@pytest.mark.asyncio
async def test_session_repo_round_trip_and_lookup_by_token(migrated_engine: object) -> None:
    factory = async_sessionmaker(migrated_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]
    uow = SqlAlchemyUnitOfWork(factory)
    user = _new_user("sess@example.com")
    sess = _make_session(user.id)

    async with uow:
        await SqlAlchemyUserRepository(uow.session).add(user)
        await SqlAlchemySessionRepository(uow.session).add(sess)
        await uow.commit()

    async with uow:
        repo = SqlAlchemySessionRepository(uow.session)
        by_id = await repo.get_by_id(sess.id)
        by_token = await repo.get_by_refresh_token_hash(sess.refresh_token_hash)
    assert by_id is not None
    assert by_token is not None
    assert by_token.id == sess.id


@pytest.mark.asyncio
async def test_session_repo_update_revokes_session(migrated_engine: object) -> None:
    factory = async_sessionmaker(migrated_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]
    user = _new_user("sessupd@example.com")
    sess = _make_session(user.id)

    setup = SqlAlchemyUnitOfWork(factory)
    async with setup:
        await SqlAlchemyUserRepository(setup.session).add(user)
        await SqlAlchemySessionRepository(setup.session).add(sess)
        await setup.commit()

    update_uow = SqlAlchemyUnitOfWork(factory)
    async with update_uow:
        repo = SqlAlchemySessionRepository(update_uow.session)
        loaded = await repo.get_by_id(sess.id)
        assert loaded is not None
        loaded.revoke()
        await repo.update(loaded)
        await update_uow.commit()

    read_uow = SqlAlchemyUnitOfWork(factory)
    async with read_uow:
        loaded = await SqlAlchemySessionRepository(read_uow.session).get_by_id(sess.id)
    assert loaded is not None
    assert loaded.revoked_at is not None


@pytest.mark.asyncio
async def test_magic_link_round_trip_and_consume(migrated_engine: object) -> None:
    factory = async_sessionmaker(migrated_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]
    user = _new_user("ml@example.com")
    now = datetime.now(UTC)
    link = MagicLink(
        id=uuid4(),
        user_id=user.id,
        token_hash=uuid4().bytes,
        mode="login",
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )

    setup = SqlAlchemyUnitOfWork(factory)
    async with setup:
        await SqlAlchemyUserRepository(setup.session).add(user)
        await SqlAlchemyMagicLinkRepository(setup.session).add(link)
        await setup.commit()

    consume_uow = SqlAlchemyUnitOfWork(factory)
    async with consume_uow:
        repo = SqlAlchemyMagicLinkRepository(consume_uow.session)
        loaded = await repo.get_by_token_hash(link.token_hash)
        assert loaded is not None
        loaded.consume()
        await repo.update(loaded)
        await consume_uow.commit()

    verify = SqlAlchemyUnitOfWork(factory)
    async with verify:
        loaded = await SqlAlchemyMagicLinkRepository(verify.session).get_by_token_hash(
            link.token_hash
        )
    assert loaded is not None
    assert loaded.consumed_at is not None


@pytest.mark.asyncio
async def test_totp_secret_round_trip_with_static_key_encryptor(
    migrated_engine: object,
) -> None:
    from vaultchain.identity.infra.totp_encryptor import StaticKeyTotpEncryptor

    factory = async_sessionmaker(migrated_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]
    encryptor = StaticKeyTotpEncryptor.from_passphrase("test-passphrase")
    user = _new_user("totp@example.com")
    plain = b"my-otp-seed"
    secret = TotpSecret.enroll(
        user_id=user.id,
        secret_plain=plain,
        backup_codes_hashed=[b"bc-1", b"bc-2"],
        encryptor=encryptor,
    )

    setup = SqlAlchemyUnitOfWork(factory)
    async with setup:
        await SqlAlchemyUserRepository(setup.session).add(user)
        await SqlAlchemyTotpSecretRepository(setup.session).add(secret)
        await setup.commit()

    read = SqlAlchemyUnitOfWork(factory)
    async with read:
        loaded = await SqlAlchemyTotpSecretRepository(read.session).get_by_user_id(user.id)
    assert loaded is not None
    assert loaded.decrypt(encryptor) == plain
    assert loaded.backup_codes_hashed == [b"bc-1", b"bc-2"]


@pytest.mark.asyncio
async def test_totp_secret_repo_update_records_last_verified_at(
    migrated_engine: object,
) -> None:
    from vaultchain.identity.infra.totp_encryptor import StaticKeyTotpEncryptor

    factory = async_sessionmaker(migrated_engine, class_=AsyncSession, expire_on_commit=False)  # type: ignore[arg-type]
    encryptor = StaticKeyTotpEncryptor.from_passphrase("p")
    user = _new_user("tot2@example.com")
    secret = TotpSecret.enroll(
        user_id=user.id,
        secret_plain=b"x",
        backup_codes_hashed=[],
        encryptor=encryptor,
    )

    setup = SqlAlchemyUnitOfWork(factory)
    async with setup:
        await SqlAlchemyUserRepository(setup.session).add(user)
        await SqlAlchemyTotpSecretRepository(setup.session).add(secret)
        await setup.commit()

    upd = SqlAlchemyUnitOfWork(factory)
    async with upd:
        secret.last_verified_at = datetime.now(UTC)
        await SqlAlchemyTotpSecretRepository(upd.session).update(secret)
        await upd.commit()

    read = SqlAlchemyUnitOfWork(factory)
    async with read:
        loaded = await SqlAlchemyTotpSecretRepository(read.session).get_by_user_id(user.id)
    assert loaded is not None
    assert loaded.last_verified_at is not None
