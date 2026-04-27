"""Infra-level outbox tests: schema contract (AC-01), backoff (AC-07), shutdown (AC-08)."""

from __future__ import annotations

import asyncio
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
from vaultchain.shared.infra.outbox_publisher import PublisherConfig, tick_once
from vaultchain.shared.infra.unit_of_work import SqlAlchemyUnitOfWork

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@register_event
@dataclass(frozen=True, kw_only=True)
class _BackoffEvent(DomainEvent):
    note: str

    aggregate_type: ClassVar[str] = "infra-test"
    event_type: ClassVar[str] = "infra.backoff_event"


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


@pytest.mark.asyncio
async def test_event_handler_log_table_and_unique_constraint(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AC-01: shared.event_handler_log exists with the documented columns +
    UNIQUE (event_id, handler_name)."""
    async with session_factory() as session:
        cols = (
            (
                await session.execute(
                    sa.text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='shared' AND table_name='event_handler_log' "
                        "ORDER BY ordinal_position"
                    )
                )
            )
            .scalars()
            .all()
        )
        constraints = (
            await session.execute(
                sa.text(
                    "SELECT con.conname, pg_get_constraintdef(con.oid) "
                    "FROM pg_constraint con "
                    "JOIN pg_class rel ON rel.oid = con.conrelid "
                    "JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace "
                    "WHERE nsp.nspname='shared' AND rel.relname='event_handler_log'"
                )
            )
        ).all()
    assert {"id", "event_id", "handler_name", "processed_at", "status"}.issubset(set(cols))
    constraint_defs = {r[0]: r[1] for r in constraints}
    assert any(
        "UNIQUE" in v and "event_id" in v and "handler_name" in v for v in constraint_defs.values()
    ), f"missing UNIQUE(event_id, handler_name): {constraint_defs}"


@pytest.mark.asyncio
async def test_backoff_skips_recently_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AC-07: with attempts=3 and base=1/factor=2 → next eligibility 8s after occurred_at.

    We seed a row, then bump attempts=3, then run a tick: the row must be
    invisible to the candidate query because backoff hasn't elapsed.
    """

    async def noop(_: object) -> None:
        return None

    bus = OutboxEventBus()
    bus.subscribe(_BackoffEvent.event_type, noop)

    uow = SqlAlchemyUnitOfWork(session_factory)
    aid = uuid4()
    async with uow:
        uow.add_event(_BackoffEvent(aggregate_id=aid, note="back"))
        await uow.commit()

    # Force the row's attempts to 3 — backoff = min(1*2^3, 60) = 8s.
    async with session_factory() as session:
        await session.execute(
            sa.text("UPDATE shared.domain_events SET attempts=3 WHERE aggregate_id=:id"),
            {"id": aid},
        )
        await session.commit()

    cfg = PublisherConfig(base_seconds=1.0, factor=2.0, max_seconds=60.0)
    async with session_factory() as session:
        result = await tick_once(session, bus, cfg=cfg)
    assert result.rows_seen == 0, "backoff window should hide the row"


@pytest.mark.asyncio
async def test_graceful_shutdown_drains_inflight(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """AC-08: cancellation mid-tick must not leave the outbox half-processed.

    `tick_once` issues a single `await session.commit()` at the very end;
    if the task is cancelled before then, no rows are written. We verify by
    cancelling immediately after starting the tick: either the tick runs
    to completion (full publish) or it yields zero side effects.
    """
    invoked: list[int] = []

    async def slow(_: object) -> None:
        invoked.append(1)
        await asyncio.sleep(0.5)  # simulate slow handler

    bus = OutboxEventBus()
    bus.subscribe(_BackoffEvent.event_type, slow)

    aid = uuid4()
    uow = SqlAlchemyUnitOfWork(session_factory)
    async with uow:
        uow.add_event(_BackoffEvent(aggregate_id=aid, note="drain"))
        await uow.commit()

    async with session_factory() as session:
        task = asyncio.create_task(tick_once(session, bus))
        await asyncio.sleep(0.1)  # let the handler start
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async with session_factory() as session:
        published_at = (
            await session.execute(
                sa.text("SELECT published_at FROM shared.domain_events " "WHERE aggregate_id=:id"),
                {"id": aid},
            )
        ).scalar_one()
    # Cancelled before commit → row stays unpublished. The handler may or may not
    # have started; the contract is that the *visible state* of the outbox is
    # consistent (no half-applied published_at without success log entry, etc.).
    assert published_at is None


def teardown_module(_module: Any) -> None:
    event_registry.pop(_BackoffEvent.event_type, None)
