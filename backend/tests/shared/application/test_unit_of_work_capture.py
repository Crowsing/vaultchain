"""Application-level UoW capture/commit/rollback semantics.

Covers AC-phase1-shared-003-04 (rollback), -06 (explicit commit + later raise),
and -07 (event payload metadata) with the `FakeUnitOfWork`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import ClassVar
from uuid import uuid4

import pytest

from tests.shared.fakes.fake_uow import FakeUnitOfWork
from vaultchain.shared.events.base import DomainEvent


@dataclass(frozen=True, kw_only=True)
class _UserCreated(DomainEvent):
    email: str

    aggregate_type: ClassVar[str] = "user"
    event_type: ClassVar[str] = "user.created"


async def _run_uow_then_raise(
    uow: FakeUnitOfWork, *, commit_first: bool, aid_email: tuple[object, str]
) -> None:
    aid, email = aid_email
    async with uow:
        uow.add_event(_UserCreated(aggregate_id=aid, email=email))  # type: ignore[arg-type]
        if commit_first:
            await uow.commit()
        raise RuntimeError("body raises")


@pytest.mark.asyncio
async def test_event_added_then_rollback_does_not_persist() -> None:
    """AC-04: body raises → rollback discards captured events."""
    uow = FakeUnitOfWork()
    with pytest.raises(RuntimeError):
        await _run_uow_then_raise(uow, commit_first=False, aid_email=(uuid4(), "a@example.com"))
    assert uow.committed_events == []
    assert uow.rollbacks == 1


@pytest.mark.asyncio
async def test_event_added_after_explicit_commit_persists() -> None:
    """AC-06: explicit commit() is durable even if a later statement raises."""
    uow = FakeUnitOfWork()
    aid = uuid4()
    with pytest.raises(RuntimeError):
        await _run_uow_then_raise(uow, commit_first=True, aid_email=(aid, "b@example.com"))
    assert len(uow.committed_events) == 1
    assert uow.committed_events[0].aggregate_id == aid


@pytest.mark.asyncio
async def test_event_serialization_roundtrip() -> None:
    """AC-07: payload contains the dataclass fields minus base meta fields."""
    aid = uuid4()
    evt = _UserCreated(aggregate_id=aid, email="c@example.com")
    raw = dataclasses.asdict(evt)
    assert raw["email"] == "c@example.com"
    assert raw["aggregate_id"] == aid
    # The serialization helper used by SqlAlchemyUnitOfWork drops these:
    from vaultchain.shared.infra.unit_of_work import (
        _serialize_payload,  # type: ignore[attr-defined]
    )

    payload = _serialize_payload(evt)
    assert "aggregate_id" not in payload
    assert "occurred_at" not in payload
    assert "event_id" not in payload
    assert payload["email"] == "c@example.com"


@pytest.mark.asyncio
async def test_add_event_rejects_unset_metadata() -> None:
    """A DomainEvent subclass without aggregate_type/event_type can't be added."""

    @dataclass(frozen=True, kw_only=True)
    class _NoMeta(DomainEvent):
        pass

    uow = FakeUnitOfWork()
    async with uow:
        with pytest.raises(TypeError, match="aggregate_type"):
            uow.add_event(_NoMeta(aggregate_id=uuid4()))
