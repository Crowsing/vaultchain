"""Outbox publisher — read unpublished events, dispatch to registered handlers,
mark `published_at` or increment `attempts` with structured logging.

The single tick (`tick_once`) is exposed as a pure async function so the
worker (arq, in-process loop, manual run) is just a thin wrapper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from vaultchain.shared.events.backoff import (
    DEFAULT_BASE_SECONDS,
    DEFAULT_FACTOR,
    DEFAULT_MAX_SECONDS,
    backoff_seconds,
)
from vaultchain.shared.events.bus import EventBus
from vaultchain.shared.events.registry import event_registry

_log = structlog.get_logger(__name__)

POLL_LIMIT = 100


@dataclass(frozen=True)
class PublisherConfig:
    base_seconds: float = DEFAULT_BASE_SECONDS
    factor: float = DEFAULT_FACTOR
    max_seconds: float = DEFAULT_MAX_SECONDS
    poll_limit: int = POLL_LIMIT


@dataclass
class TickResult:
    rows_seen: int = 0
    rows_published: int = 0
    rows_skipped_no_handler: int = 0
    rows_failed: int = 0
    rows_short_circuited: int = 0
    seen_event_ids: list[UUID] = field(default_factory=list)


def _candidate_query(cfg: PublisherConfig) -> sa.TextClause:
    """Select unpublished rows whose backoff window has elapsed.

    Fresh rows (attempts=0) are immediately eligible. Retried rows wait
    `base * factor**attempts` seconds (capped at `max`) past `occurred_at`.
    """
    return sa.text(
        """
        SELECT id, aggregate_id, aggregate_type, event_type, payload,
               occurred_at, attempts
          FROM shared.domain_events
         WHERE published_at IS NULL
           AND (
                attempts = 0
                OR occurred_at + (
                    LEAST(:base * POWER(:factor, attempts), :max_s)
                    * INTERVAL '1 second'
                ) <= NOW()
           )
         ORDER BY occurred_at
         LIMIT :limit
         FOR UPDATE SKIP LOCKED
        """
    )


def _reconstruct_event(row: sa.Row[Any]) -> object | None:
    """Rebuild a DomainEvent from a row; returns None if `event_type` is unknown."""
    cls = event_registry.get(row.event_type)
    if cls is None:
        return None
    payload = dict(row.payload or {})
    return cls(
        aggregate_id=row.aggregate_id,
        occurred_at=row.occurred_at,
        event_id=row.id,
        **payload,
    )


async def _claim_handler(
    session: AsyncSession, event_id: UUID, handler_name: str, status: str
) -> bool:
    """ON CONFLICT DO NOTHING — returns True iff this caller now owns the slot."""
    result = await session.execute(
        sa.text(
            """
            INSERT INTO shared.event_handler_log
                   (event_id, handler_name, status)
            VALUES (:event_id, :handler, :status)
            ON CONFLICT (event_id, handler_name) DO NOTHING
            """
        ),
        {"event_id": event_id, "handler": handler_name, "status": status},
    )
    return bool(getattr(result, "rowcount", 0))


async def tick_once(
    session: AsyncSession,
    bus: EventBus,
    *,
    cfg: PublisherConfig | None = None,
) -> TickResult:
    """One pass over the outbox; returns counters for observability."""
    cfg = cfg or PublisherConfig()
    out = TickResult()

    rows = (
        await session.execute(
            _candidate_query(cfg),
            {
                "base": cfg.base_seconds,
                "factor": cfg.factor,
                "max_s": cfg.max_seconds,
                "limit": cfg.poll_limit,
            },
        )
    ).all()

    for row in rows:
        out.rows_seen += 1
        out.seen_event_ids.append(row.id)
        event_obj = _reconstruct_event(row)
        if event_obj is None:
            _log.warning(
                "outbox.unknown_event_type", event_id=str(row.id), event_type=row.event_type
            )
            await session.execute(
                sa.text("UPDATE shared.domain_events SET published_at=NOW() WHERE id=:id"),
                {"id": row.id},
            )
            out.rows_skipped_no_handler += 1
            continue

        handlers = bus.handlers_for(row.event_type)
        if not handlers:
            await session.execute(
                sa.text("UPDATE shared.domain_events SET published_at=NOW() WHERE id=:id"),
                {"id": row.id},
            )
            out.rows_skipped_no_handler += 1
            _log.info(
                "outbox.no_handler",
                event_id=str(row.id),
                event_type=row.event_type,
            )
            continue

        any_failure = False
        all_short_circuited = True
        for handler in handlers:
            handler_name = getattr(handler, "__qualname__", repr(handler))
            claimed = await _claim_handler(session, row.id, handler_name, "in_progress")
            if not claimed:
                out.rows_short_circuited += 1
                _log.info(
                    "outbox.replay_short_circuit",
                    event_id=str(row.id),
                    event_type=row.event_type,
                    handler_name=handler_name,
                )
                continue
            all_short_circuited = False
            try:
                await handler(event_obj)  # type: ignore[arg-type]
            except Exception as exc:
                any_failure = True
                err = str(exc)[:1024]
                _log.warning(
                    "outbox.handler_failed",
                    event_id=str(row.id),
                    event_type=row.event_type,
                    handler_name=handler_name,
                    attempt=row.attempts,
                    error_class=type(exc).__qualname__,
                )
                await session.execute(
                    sa.text(
                        "DELETE FROM shared.event_handler_log "
                        "WHERE event_id=:eid AND handler_name=:h"
                    ),
                    {"eid": row.id, "h": handler_name},
                )
                await session.execute(
                    sa.text(
                        "UPDATE shared.domain_events "
                        "SET attempts = attempts + 1, last_error = :err "
                        "WHERE id=:id"
                    ),
                    {"id": row.id, "err": err},
                )
                break
            else:
                await session.execute(
                    sa.text(
                        "UPDATE shared.event_handler_log SET status='success' "
                        "WHERE event_id=:eid AND handler_name=:h"
                    ),
                    {"eid": row.id, "h": handler_name},
                )
                _log.info(
                    "outbox.handler_succeeded",
                    event_id=str(row.id),
                    event_type=row.event_type,
                    handler_name=handler_name,
                    attempt=row.attempts,
                    status="success",
                )

        if any_failure:
            out.rows_failed += 1
        else:
            await session.execute(
                sa.text("UPDATE shared.domain_events SET published_at=NOW() WHERE id=:id"),
                {"id": row.id},
            )
            if all_short_circuited:
                # All handlers had already run — count as published.
                pass
            out.rows_published += 1

    await session.commit()
    return out


__all__ = [
    "POLL_LIMIT",
    "PublisherConfig",
    "TickResult",
    "backoff_seconds",
    "tick_once",
]
