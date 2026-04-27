"""Concrete in-process `EventBus` adapter.

Maintains a `dict[event_type, list[handler]]` registry; `publish()` walks the
list serially. The publisher worker uses `handlers_for(event_type)` to fan
out outbox events; subscribers register at app startup.
"""

from __future__ import annotations

from collections import defaultdict

from vaultchain.shared.events.base import DomainEvent
from vaultchain.shared.events.bus import EventHandler


class OutboxEventBus:
    """In-process event bus. Subscribers are async callables."""

    def __init__(self) -> None:
        self._subs: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        if handler in self._subs[event_type]:
            return
        self._subs[event_type].append(handler)

    def handlers_for(self, event_type: str) -> tuple[EventHandler, ...]:
        return tuple(self._subs.get(event_type, ()))

    async def publish(self, event: DomainEvent) -> None:
        for handler in self.handlers_for(event.event_type):
            await handler(event)


__all__ = ["OutboxEventBus"]
