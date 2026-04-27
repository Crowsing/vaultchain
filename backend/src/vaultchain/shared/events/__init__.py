"""Domain events — base class + registry."""

from vaultchain.shared.events.base import DomainEvent
from vaultchain.shared.events.registry import event_registry, register_event

__all__ = ["DomainEvent", "event_registry", "register_event"]
