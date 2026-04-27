"""In-memory `FakeUnitOfWork` for unit-level tests of capture / commit / rollback semantics."""

from __future__ import annotations

from types import TracebackType

from vaultchain.shared.events.base import DomainEvent


class FakeUnitOfWork:
    """Mimics the UoW Protocol; persists `committed_events` once commit() is called."""

    def __init__(self) -> None:
        self._buffered: list[DomainEvent] = []
        self.committed_events: list[DomainEvent] = []
        self.rollbacks = 0
        self.entered = False

    async def __aenter__(self) -> FakeUnitOfWork:
        self.entered = True
        self._buffered = []
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()
        self.entered = False

    async def commit(self) -> None:
        self.committed_events.extend(self._buffered)
        self._buffered = []

    async def rollback(self) -> None:
        self._buffered = []
        self.rollbacks += 1

    def add_event(self, event: DomainEvent) -> None:
        if not event.aggregate_type or not event.event_type:
            raise TypeError("FakeUoW requires aggregate_type and event_type to be set")
        self._buffered.append(event)
