"""Event registry — `event_type` (string) → concrete `DomainEvent` subclass.

Used at deserialization time (e.g. by the outbox worker in `phase1-shared-004`)
to reconstruct a typed event from a `shared.domain_events` row.
"""

from __future__ import annotations

from typing import TypeVar

from vaultchain.shared.events.base import DomainEvent

_E = TypeVar("_E", bound=DomainEvent)

event_registry: dict[str, type[DomainEvent]] = {}


def register_event(cls: type[_E]) -> type[_E]:
    """Class decorator: index a concrete event class by its `event_type` string."""
    if not cls.event_type:
        raise TypeError(f"{cls.__qualname__} must set a non-empty event_type")
    if cls.event_type in event_registry and event_registry[cls.event_type] is not cls:
        raise TypeError(
            f"event_type {cls.event_type!r} already registered to "
            f"{event_registry[cls.event_type].__qualname__}"
        )
    event_registry[cls.event_type] = cls
    return cls


__all__ = ["event_registry", "register_event"]
