"""DomainEvent base — atomic outbox capture pattern.

Concrete events subclass `DomainEvent`, override the `aggregate_type` and
`event_type` class vars, and add their own dataclass fields for payload data.
The UoW captures events in-memory, then writes them to `shared.domain_events`
inside the same SQL transaction as the aggregate mutation (architecture
decision Section 3, "outbox pattern").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID, uuid4


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    """Base class for domain events. Subclasses set `aggregate_type` and
    `event_type` class variables and add additional payload fields."""

    aggregate_id: UUID
    occurred_at: datetime = field(default_factory=_utc_now)
    event_id: UUID = field(default_factory=uuid4)

    aggregate_type: ClassVar[str] = ""
    event_type: ClassVar[str] = ""


__all__ = ["DomainEvent"]
