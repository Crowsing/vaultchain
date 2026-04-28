"""`AbstractUnitOfWork` Protocol — the contract every concrete UoW satisfies.

Application use cases depend on this Protocol, never on `SqlAlchemyUnitOfWork`
directly, so domain code never imports infra. The concrete adapter lives in
`vaultchain.shared.infra.unit_of_work`.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Protocol, runtime_checkable

from vaultchain.shared.events.base import DomainEvent


@runtime_checkable
class AbstractUnitOfWork(Protocol):
    """Async context-managed transaction scope.

    Lifecycle:
        async with uow:           # __aenter__: open session
            do_things(uow)
            uow.add_event(evt)    # captured in-memory
            await uow.commit()    # writes events alongside aggregate rows
                                  # __aexit__: close session (auto-rollback if body raised)
    """

    @property
    def session(self) -> Any:
        """Session-like handle that repository factories bind to.

        Typed `Any` so the Protocol stays database-agnostic; the concrete
        adapter exposes `AsyncSession`, the in-memory test fake exposes a
        sentinel that the test repo factory ignores.
        """
        ...

    async def __aenter__(self) -> AbstractUnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    def add_event(self, event: DomainEvent) -> None: ...


__all__ = ["AbstractUnitOfWork"]
