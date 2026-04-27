"""Application-level outbox publisher loop tests using a real Postgres
container (testcontainers) — covers AC-phase1-shared-004-02..-06.

These live under `application/` because they exercise the publisher's
behavior contract end-to-end with the registry + bus, only using Postgres
as the persistence substrate.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from vaultchain.shared.events.base import DomainEvent
from vaultchain.shared.events.registry import event_registry, register_event
from vaultchain.shared.infra.event_bus import OutboxEventBus
from vaultchain.shared.infra.outbox_publisher import tick_once
from vaultchain.shared.infra.unit_of_work import SqlAlchemyUnitOfWork

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@register_event
@dataclass(frozen=True, kw_only=True)
class _UserCreated(DomainEvent):
    email: str

    aggregate_type: ClassVar[str] = "user"
    event_type: ClassVar[str] = "user.created_via_outbox_test"


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
    sync = raw.replace("postgresql+psycopg2://", "postgresql://")
    return sync.replace("postgresql://", "postgresql+asyncpg://")


@pytest_asyncio.fixture
async def session_factory(
    async_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    monkeypatch.setenv("DATABASE_URL", async_dsn)
    cfg = _alembic_config(async_dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_async_engine(async_dsn, future=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        await asyncio.to_thread(command.downgrade, cfg, "base")


async def _seed_event(factory: async_sessionmaker[AsyncSession], event: _UserCreated) -> None:
    uow = SqlAlchemyUnitOfWork(factory)
    async with uow:
        uow.add_event(event)
        await uow.commit()


@pytest.mark.asyncio
async def test_dispatch_to_registered_handler(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AC-02: handler invoked exactly once with deserialized payload."""
    received: list[_UserCreated] = []

    async def on_user_created(evt: object) -> None:
        assert isinstance(evt, _UserCreated)
        received.append(evt)

    bus = OutboxEventBus()
    bus.subscribe(_UserCreated.event_type, on_user_created)

    aid = uuid4()
    await _seed_event(session_factory, _UserCreated(aggregate_id=aid, email="d@example.com"))

    async with session_factory() as session:
        result = await tick_once(session, bus)
    assert result.rows_published == 1
    assert len(received) == 1
    assert received[0].email == "d@example.com"
    assert received[0].aggregate_id == aid


@pytest.mark.asyncio
async def test_handler_success_marks_published(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AC-03: published_at set + event_handler_log status='success'."""

    async def on_user_created(_: object) -> None:
        return None

    bus = OutboxEventBus()
    bus.subscribe(_UserCreated.event_type, on_user_created)

    aid = uuid4()
    await _seed_event(session_factory, _UserCreated(aggregate_id=aid, email="s@example.com"))

    async with session_factory() as session:
        await tick_once(session, bus)
    async with session_factory() as session:
        published_at, attempts = (
            await session.execute(
                sa.text(
                    "SELECT published_at, attempts FROM shared.domain_events "
                    "WHERE aggregate_id=:id"
                ),
                {"id": aid},
            )
        ).one()
        log_status = (
            await session.execute(
                sa.text(
                    "SELECT status FROM shared.event_handler_log "
                    "WHERE event_id=(SELECT id FROM shared.domain_events WHERE aggregate_id=:id)"
                ),
                {"id": aid},
            )
        ).scalar_one()
    assert published_at is not None
    assert attempts == 0
    assert log_status == "success"


@pytest.mark.asyncio
async def test_handler_failure_increments_attempts_and_records_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AC-04: handler raise → published_at NULL, attempts+1, last_error set."""

    async def boom(_: object) -> None:
        raise RuntimeError("synthetic handler failure")

    bus = OutboxEventBus()
    bus.subscribe(_UserCreated.event_type, boom)

    aid = uuid4()
    await _seed_event(session_factory, _UserCreated(aggregate_id=aid, email="f@example.com"))
    async with session_factory() as session:
        result = await tick_once(session, bus)
    assert result.rows_failed == 1
    async with session_factory() as session:
        row = (
            await session.execute(
                sa.text(
                    "SELECT published_at, attempts, last_error "
                    "FROM shared.domain_events WHERE aggregate_id=:id"
                ),
                {"id": aid},
            )
        ).one()
        log_count = (
            await session.execute(
                sa.text(
                    "SELECT COUNT(*) FROM shared.event_handler_log "
                    "WHERE event_id=(SELECT id FROM shared.domain_events WHERE aggregate_id=:id)"
                ),
                {"id": aid},
            )
        ).scalar_one()
    assert row[0] is None
    assert row[1] == 1
    assert "synthetic" in row[2]
    # We rolled back the in_progress row so retry can re-claim it.
    assert log_count == 0


@pytest.mark.asyncio
async def test_redelivery_short_circuits_via_handler_log(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AC-05: second delivery hits the UNIQUE and skips re-running the handler."""
    invocations = 0

    async def count(_: object) -> None:
        nonlocal invocations
        invocations += 1

    bus = OutboxEventBus()
    bus.subscribe(_UserCreated.event_type, count)

    aid = uuid4()
    await _seed_event(session_factory, _UserCreated(aggregate_id=aid, email="r@example.com"))
    async with session_factory() as session:
        await tick_once(session, bus)
    # Manually clear `published_at` to force the publisher to re-evaluate.
    async with session_factory() as session:
        await session.execute(
            sa.text("UPDATE shared.domain_events SET published_at=NULL WHERE aggregate_id=:id"),
            {"id": aid},
        )
        await session.commit()
    async with session_factory() as session:
        result = await tick_once(session, bus)
    assert invocations == 1
    assert result.rows_short_circuited >= 1


@pytest.mark.asyncio
async def test_event_with_no_handler_marked_published(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AC-06: no subscriber → no-op-safe; row is marked published, not retried."""
    bus = OutboxEventBus()
    aid = uuid4()
    await _seed_event(session_factory, _UserCreated(aggregate_id=aid, email="n@example.com"))
    async with session_factory() as session:
        result = await tick_once(session, bus)
    assert result.rows_skipped_no_handler == 1
    async with session_factory() as session:
        published_at = (
            await session.execute(
                sa.text("SELECT published_at FROM shared.domain_events " "WHERE aggregate_id=:id"),
                {"id": aid},
            )
        ).scalar_one()
    assert published_at is not None


# Ensure registration cleanup so other test modules aren't affected.
def teardown_module(_module: Any) -> None:
    event_registry.pop(_UserCreated.event_type, None)


# Touch dataclasses so import-organizers don't drop it (we use kw-only sub-instantiation).
_ = dataclasses
