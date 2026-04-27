"""arq worker entrypoint — runs the outbox publisher tick on a schedule.

Discoverable via `arq vaultchain.worker.WorkerSettings`. AC-phase1-shared-004-08
expects graceful shutdown to drain in-flight handler invocations: the single
tick is one transaction, so SIGTERM during a tick will let it complete via
`session.commit()` before the loop exits.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import structlog
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vaultchain.shared.infra.event_bus import OutboxEventBus
from vaultchain.shared.infra.outbox_publisher import PublisherConfig, tick_once

_log = structlog.get_logger(__name__)


async def outbox_publisher_tick(ctx: dict[str, Any]) -> dict[str, int]:
    factory: async_sessionmaker[AsyncSession] = ctx["session_factory"]
    bus: OutboxEventBus = ctx["event_bus"]
    cfg: PublisherConfig = ctx["publisher_cfg"]
    async with factory() as session:
        result = await tick_once(session, bus, cfg=cfg)
    _log.info(
        "outbox.tick",
        seen=result.rows_seen,
        published=result.rows_published,
        failed=result.rows_failed,
        skipped=result.rows_skipped_no_handler,
        short_circuited=result.rows_short_circuited,
    )
    return {
        "seen": result.rows_seen,
        "published": result.rows_published,
        "failed": result.rows_failed,
        "skipped": result.rows_skipped_no_handler,
        "short_circuited": result.rows_short_circuited,
    }


async def _startup(ctx: dict[str, Any]) -> None:
    db_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://vaultchain:dev@localhost:5432/vaultchain"
    )
    engine = create_async_engine(db_url, future=True)
    ctx["engine"] = engine
    ctx["session_factory"] = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx["event_bus"] = OutboxEventBus()
    ctx["publisher_cfg"] = PublisherConfig()


async def _shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("engine")
    if engine is not None:
        await engine.dispose()


class WorkerSettings:
    functions: Sequence[Any] = [outbox_publisher_tick]
    cron_jobs: Sequence[Any] = [
        cron(outbox_publisher_tick, second=set(range(60)), run_at_startup=True),
    ]
    on_startup = _startup
    on_shutdown = _shutdown
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = 1
