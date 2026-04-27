"""Real-Postgres adapter tests for `SqlAlchemyUnitOfWork` + outbox migration.

Covers AC-phase1-shared-003-01 through -05, -07, and -08 against a Postgres 16
container. Each test starts from a freshly-migrated DB.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from vaultchain.shared.domain.errors import StaleAggregate
from vaultchain.shared.events.base import DomainEvent
from vaultchain.shared.infra.unit_of_work import SqlAlchemyUnitOfWork

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@dataclass(frozen=True, kw_only=True)
class _UserCreated(DomainEvent):
    email: str

    aggregate_type: ClassVar[str] = "user"
    event_type: ClassVar[str] = "user.created"


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
def sync_dsn(pg_container: PostgresContainer) -> str:
    raw = pg_container.get_connection_url()
    # testcontainers gives `postgresql+psycopg2://...`; strip the driver
    # for the alembic env.py override below where we use psycopg / asyncpg.
    return raw.replace("postgresql+psycopg2://", "postgresql://")


@pytest.fixture(scope="module")
def async_dsn(sync_dsn: str) -> str:
    return sync_dsn.replace("postgresql://", "postgresql+asyncpg://")


@pytest_asyncio.fixture
async def migrated_engine(
    sync_dsn: str, async_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[object]:
    """Apply the migration; yield a fresh async engine; downgrade after.

    `env.py` reads `DATABASE_URL` first (Phase 1 contract), so we surface the
    testcontainer DSN through the env var rather than via `set_main_option`,
    which only touches the in-memory main options dict and is not visible to
    `config.get_section()` that `async_engine_from_config` consumes.
    """
    monkeypatch.setenv("DATABASE_URL", async_dsn)
    cfg = _alembic_config(async_dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_async_engine(async_dsn, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()
        await asyncio.to_thread(command.downgrade, cfg, "base")


@pytest.mark.asyncio
async def test_migration_creates_shared_schema_and_table(migrated_engine: object) -> None:
    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        schemas = (
            (await conn.execute(sa.text("SELECT schema_name FROM information_schema.schemata")))
            .scalars()
            .all()
        )
        assert "shared" in schemas
        cols = (
            await conn.execute(
                sa.text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema='shared' AND table_name='domain_events' "
                    "ORDER BY ordinal_position"
                )
            )
        ).all()
    names = {c[0] for c in cols}
    assert names == {
        "id",
        "aggregate_id",
        "aggregate_type",
        "event_type",
        "payload",
        "occurred_at",
        "published_at",
        "attempts",
        "last_error",
    }


@pytest.mark.asyncio
async def test_migration_creates_partial_index(migrated_engine: object) -> None:
    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname='shared' AND tablename='domain_events'"
                )
            )
        ).all()
    by_name = {r[0]: r[1] for r in rows}
    assert "idx_events_unpublished" in by_name
    idx_def = by_name["idx_events_unpublished"]
    assert "published_at IS NULL" in idx_def
    assert "(published_at, occurred_at)" in idx_def or "published_at, occurred_at" in idx_def


@pytest.mark.asyncio
async def test_downgrade_removes_table_and_schema(
    sync_dsn: str, async_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", async_dsn)
    cfg = _alembic_config(async_dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.downgrade, cfg, "base")
    engine = create_async_engine(async_dsn, future=True)
    try:
        async with engine.connect() as conn:
            schemas = (
                (await conn.execute(sa.text("SELECT schema_name FROM information_schema.schemata")))
                .scalars()
                .all()
            )
            assert "shared" not in schemas
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_uow_rollback_on_exception_leaves_table_empty(migrated_engine: object) -> None:
    engine = migrated_engine
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    uow = SqlAlchemyUnitOfWork(factory)

    async def _run() -> None:
        async with uow:
            uow.add_event(_UserCreated(aggregate_id=uuid4(), email="rb@example.com"))
            raise RuntimeError("body explodes before commit")

    with pytest.raises(RuntimeError):
        await _run()
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        n = (await conn.execute(sa.text("SELECT COUNT(*) FROM shared.domain_events"))).scalar_one()
    assert n == 0


@pytest.mark.asyncio
async def test_uow_atomic_aggregate_and_event_write(migrated_engine: object) -> None:
    """AC-05: aggregate row + event row visible from a separate connection after commit."""
    engine = migrated_engine
    # test-only aggregate table to avoid coupling this brief to any future schema.
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.execute(
            sa.text(
                "CREATE TABLE IF NOT EXISTS test_users ("
                "  id UUID PRIMARY KEY,"
                "  email TEXT NOT NULL,"
                "  version INTEGER NOT NULL DEFAULT 1"
                ")"
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    uow = SqlAlchemyUnitOfWork(factory)
    aid = uuid4()
    async with uow:
        await uow.session.execute(
            sa.text("INSERT INTO test_users (id, email) VALUES (:id, :email)"),
            {"id": aid, "email": "ok@example.com"},
        )
        uow.add_event(_UserCreated(aggregate_id=aid, email="ok@example.com"))
        await uow.commit()
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        users = (
            await conn.execute(sa.text("SELECT email FROM test_users WHERE id=:id"), {"id": aid})
        ).scalar_one()
        evt = (
            await conn.execute(
                sa.text(
                    "SELECT aggregate_type, event_type, payload "
                    "FROM shared.domain_events WHERE aggregate_id=:id"
                ),
                {"id": aid},
            )
        ).one()
    assert users == "ok@example.com"
    assert evt[0] == "user"
    assert evt[1] == "user.created"
    assert evt[2] == {"email": "ok@example.com"}
    # cleanup
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.execute(sa.text("DROP TABLE IF EXISTS test_users"))


@pytest.mark.asyncio
async def test_event_payload_serialization_in_db(migrated_engine: object) -> None:
    engine = migrated_engine
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    uow = SqlAlchemyUnitOfWork(factory)
    aid = uuid4()
    async with uow:
        uow.add_event(_UserCreated(aggregate_id=aid, email="srz@example.com"))
        await uow.commit()
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        row = (
            await conn.execute(
                sa.text(
                    "SELECT aggregate_id, aggregate_type, event_type, payload "
                    "FROM shared.domain_events WHERE aggregate_id=:id"
                ),
                {"id": aid},
            )
        ).one()
    assert row[0] == aid
    assert row[1] == "user"
    assert row[2] == "user.created"
    assert row[3] == {"email": "srz@example.com"}


@pytest.mark.asyncio
async def test_optimistic_lock_concurrent_update_raises_stale(
    migrated_engine: object,
) -> None:
    """AC-08: two writers reading the same version, only one wins."""
    engine = migrated_engine
    aid = uuid4()
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.execute(
            sa.text(
                "CREATE TABLE IF NOT EXISTS test_optlock ("
                "  id UUID PRIMARY KEY,"
                "  payload TEXT NOT NULL,"
                "  version INTEGER NOT NULL DEFAULT 1"
                ")"
            )
        )
        await conn.execute(
            sa.text("INSERT INTO test_optlock (id, payload) VALUES (:id, :p)"),
            {"id": aid, "p": "v1"},
        )

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def attempt_update(new_payload: str) -> bool:
        uow = SqlAlchemyUnitOfWork(factory)
        async with uow:
            res = await uow.session.execute(
                sa.text(
                    "UPDATE test_optlock SET payload=:p, version=version+1 "
                    "WHERE id=:id AND version=1"
                ),
                {"p": new_payload, "id": aid},
            )
            if res.rowcount == 0:
                raise StaleAggregate(details={"aggregate_id": str(aid)})
            await uow.commit()
            return True

    a, b = await asyncio.gather(
        attempt_update("v2-A"),
        attempt_update("v2-B"),
        return_exceptions=True,
    )
    successes = [r for r in (a, b) if r is True]
    failures = [r for r in (a, b) if isinstance(r, StaleAggregate)]
    assert len(successes) == 1
    assert len(failures) == 1

    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.execute(sa.text("DROP TABLE IF EXISTS test_optlock"))
