"""Domain Protocol shape for `EventBus` (AC-phase1-shared-004-02 setup)."""

from __future__ import annotations

import inspect
from typing import Protocol


def test_event_bus_publish_signature() -> None:
    from vaultchain.shared.events.bus import EventBus

    assert issubclass(EventBus, Protocol)  # type: ignore[arg-type]
    assert inspect.iscoroutinefunction(EventBus.publish)
    sig = inspect.signature(EventBus.publish)
    assert list(sig.parameters) == ["self", "event"]


def test_event_bus_subscribe_signature() -> None:
    from vaultchain.shared.events.bus import EventBus

    assert callable(EventBus.subscribe)
    sig = inspect.signature(EventBus.subscribe)
    assert list(sig.parameters) == ["self", "event_type", "handler"]


def test_outbox_event_bus_satisfies_protocol() -> None:
    from vaultchain.shared.events.bus import EventBus
    from vaultchain.shared.infra.event_bus import OutboxEventBus

    bus = OutboxEventBus()
    assert isinstance(bus, EventBus)


def test_event_bus_handlers_for_isolation() -> None:
    """Subscriptions are per-event-type and dedup'd."""
    from vaultchain.shared.infra.event_bus import OutboxEventBus

    bus = OutboxEventBus()

    async def h(_: object) -> None:
        return None

    bus.subscribe("a.created", h)
    bus.subscribe("a.created", h)  # idempotent
    bus.subscribe("b.created", h)
    assert bus.handlers_for("a.created") == (h,)
    assert bus.handlers_for("b.created") == (h,)
    assert bus.handlers_for("c.created") == ()
