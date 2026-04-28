"""In-memory `AbstractUnitOfWork` for application-layer unit tests.

Captures events the use case adds; commit/rollback toggle observable
flags so tests can assert that the use case actually committed and
that exceptions correctly trigger rollback.
"""

from __future__ import annotations

from types import TracebackType

from vaultchain.shared.events.base import DomainEvent


class FakeUnitOfWork:
    """No-DB `AbstractUnitOfWork` — pure in-memory event capture."""

    def __init__(self) -> None:
        self.committed: bool = False
        self.rolled_back: bool = False
        self.captured_events: list[DomainEvent] = []
        self._entered: bool = False

    async def __aenter__(self) -> FakeUnitOfWork:
        self._entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None and not self.committed:
            self.rolled_back = True
            self.captured_events = []

    @property
    def session(self) -> object:
        # Production session-bound repos use this; in unit tests the repo
        # factory ignores the session and closes over an in-memory store.
        return object()

    def add_event(self, event: DomainEvent) -> None:
        self.captured_events.append(event)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True
        self.captured_events = []
