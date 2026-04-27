"""Hypothesis property: DomainEvent payload serialization is round-trippable.

Property: for any concrete `DomainEvent` dataclass with primitive fields,
`asdict → json → jsonb → dict → reconstructed_event` preserves field equality.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vaultchain.shared.events.base import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _SampleEvent(DomainEvent):
    name: str
    amount: int
    flag: bool

    aggregate_type: ClassVar[str] = "sample"
    event_type: ClassVar[str] = "sample.created"


def _serialize(event: DomainEvent) -> str:
    raw = dataclasses.asdict(event)
    return json.dumps(raw, default=str, sort_keys=True)


def _reconstruct(serialized: str, cls: type[_SampleEvent]) -> _SampleEvent:
    data = json.loads(serialized)
    return cls(
        aggregate_id=UUID(data["aggregate_id"]),
        occurred_at=datetime.fromisoformat(data["occurred_at"]),
        event_id=UUID(data["event_id"]),
        name=data["name"],
        amount=data["amount"],
        flag=data["flag"],
    )


@pytest.mark.property
@settings(max_examples=100, deadline=1000)
@given(
    name=st.text(min_size=0, max_size=128),
    amount=st.integers(min_value=-(2**31), max_value=2**31 - 1),
    flag=st.booleans(),
)
def test_domain_event_roundtrip_preserves_equality(name: str, amount: int, flag: bool) -> None:
    original = _SampleEvent(
        aggregate_id=uuid4(),
        occurred_at=datetime.now(UTC),
        event_id=uuid4(),
        name=name,
        amount=amount,
        flag=flag,
    )
    rebuilt = _reconstruct(_serialize(original), _SampleEvent)
    assert rebuilt == original
    assert rebuilt.aggregate_type == original.aggregate_type
    assert rebuilt.event_type == original.event_type


def test_register_event_indexes_by_event_type() -> None:
    from vaultchain.shared.events.registry import event_registry, register_event

    @register_event
    @dataclass(frozen=True, kw_only=True)
    class _Reg(DomainEvent):
        aggregate_type: ClassVar[str] = "reg-test"
        event_type: ClassVar[str] = "reg.test_created"
        note: str = field(default="")

    try:
        assert event_registry["reg.test_created"] is _Reg
    finally:
        event_registry.pop("reg.test_created", None)


def test_register_event_rejects_empty_event_type() -> None:
    from vaultchain.shared.events.registry import register_event

    @dataclass(frozen=True, kw_only=True)
    class _NoType(DomainEvent):
        pass

    with pytest.raises(TypeError, match="non-empty event_type"):
        register_event(_NoType)
