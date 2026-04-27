"""`SqlAlchemyUnitOfWork` — async concrete adapter for the UoW Protocol.

Captures `DomainEvent`s in memory; on `commit()` writes them as rows in
`shared.domain_events` *before* issuing SQL `COMMIT`, so events land
atomically with the aggregate write. On rollback (explicit or on
exception) the captured event buffer is discarded.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from types import TracebackType
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vaultchain.shared.events.base import DomainEvent
from vaultchain.shared.infra.database import DomainEventRow

_BASE_FIELD_NAMES = {"aggregate_id", "occurred_at", "event_id"}


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "hex") and hasattr(obj, "int"):  # uuid.UUID
        return str(obj)
    raise TypeError(f"Cannot JSON-encode value of type {type(obj).__name__}")


def _serialize_payload(event: DomainEvent) -> dict[str, Any]:
    """Drop the meta fields and round-trip the rest through JSON for JSONB."""
    raw = dataclasses.asdict(event)
    payload = {k: v for k, v in raw.items() if k not in _BASE_FIELD_NAMES}
    serialized: dict[str, Any] = json.loads(json.dumps(payload, default=_json_default))
    return serialized


class SqlAlchemyUnitOfWork:
    """One UoW instance == one short-lived `AsyncSession` + one transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._events: list[DomainEvent] = []

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self._events = []
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        try:
            if exc_type is not None:
                await self._session.rollback()
                self._events = []
        finally:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UoW not entered — use `async with uow:`")
        return self._session

    @property
    def captured_events(self) -> tuple[DomainEvent, ...]:
        return tuple(self._events)

    def add_event(self, event: DomainEvent) -> None:
        if not event.aggregate_type or not event.event_type:
            raise TypeError(
                f"DomainEvent {type(event).__qualname__} must set aggregate_type and event_type"
            )
        self._events.append(event)

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("UoW not entered")
        for event in self._events:
            self._session.add(
                DomainEventRow(
                    aggregate_id=event.aggregate_id,
                    aggregate_type=event.aggregate_type,
                    event_type=event.event_type,
                    payload=_serialize_payload(event),
                    occurred_at=event.occurred_at,
                )
            )
        self._events = []
        await self._session.commit()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("UoW not entered")
        await self._session.rollback()
        self._events = []


__all__ = ["SqlAlchemyUnitOfWork"]
