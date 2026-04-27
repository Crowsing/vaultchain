"""Domain events — base class, registry, and bus Protocol."""

from vaultchain.shared.events.base import DomainEvent
from vaultchain.shared.events.bus import EventBus, EventHandler
from vaultchain.shared.events.registry import event_registry, register_event

__all__ = [
    "DomainEvent",
    "EventBus",
    "EventHandler",
    "event_registry",
    "register_event",
]
