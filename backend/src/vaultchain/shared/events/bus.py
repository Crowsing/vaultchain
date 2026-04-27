"""`EventBus` Protocol — the dispatch contract every concrete bus satisfies.

Application code never calls `bus.publish()` directly: events go through the
UoW (`add_event`) which puts them into the outbox; the publisher worker reads
the outbox and invokes registered handlers via the bus. `publish()` exists so
synchronous callers (tests, future in-process pumps) can still dispatch.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

from vaultchain.shared.events.base import DomainEvent

EventHandler = Callable[[DomainEvent], Awaitable[None]]


@runtime_checkable
class EventBus(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...

    def subscribe(self, event_type: str, handler: EventHandler) -> None: ...

    def handlers_for(self, event_type: str) -> tuple[EventHandler, ...]: ...


__all__ = ["EventBus", "EventHandler"]
