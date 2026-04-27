"""Domain Protocol shape for `AbstractUnitOfWork` (AC-phase1-shared-003-04 setup)."""

from __future__ import annotations

import inspect
from typing import Protocol

import pytest


def test_uow_protocol_has_commit_rollback_add_event() -> None:
    from vaultchain.shared.unit_of_work.base import AbstractUnitOfWork

    assert issubclass(AbstractUnitOfWork, Protocol)  # type: ignore[arg-type]
    for name in ("commit", "rollback", "add_event"):
        assert hasattr(AbstractUnitOfWork, name), f"UoW Protocol missing {name}"


def test_uow_aenter_aexit_signature() -> None:
    from vaultchain.shared.unit_of_work.base import AbstractUnitOfWork

    assert inspect.iscoroutinefunction(AbstractUnitOfWork.__aenter__)
    assert inspect.iscoroutinefunction(AbstractUnitOfWork.__aexit__)
    sig = inspect.signature(AbstractUnitOfWork.__aexit__)
    assert list(sig.parameters) == ["self", "exc_type", "exc", "tb"]


def test_uow_protocol_runtime_checkable_against_duck_type() -> None:
    from vaultchain.shared.events.base import DomainEvent
    from vaultchain.shared.unit_of_work.base import AbstractUnitOfWork

    class _Shim:
        async def __aenter__(self) -> object:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

        def add_event(self, event: DomainEvent) -> None:
            return None

    assert isinstance(_Shim(), AbstractUnitOfWork)


def test_stale_aggregate_is_conflict_subclass() -> None:
    from vaultchain.shared.domain.errors import ConflictError, StaleAggregate

    assert issubclass(StaleAggregate, ConflictError)
    assert StaleAggregate.code == "concurrency.stale_aggregate"
    assert StaleAggregate.status_code == 409
    with pytest.raises(StaleAggregate) as ei:
        raise StaleAggregate(details={"aggregate_id": "x"})
    assert ei.value.details == {"aggregate_id": "x"}
