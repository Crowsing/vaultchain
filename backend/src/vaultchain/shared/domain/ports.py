"""Shared domain ports — protocols for cross-context infrastructure."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class CachedResponse:
    """Snapshot of an HTTP response suitable for replay."""

    status_code: int
    headers: list[tuple[str, str]]
    body: bytes


@dataclass(frozen=True, slots=True)
class StoreEntry:
    """Idempotency cache entry — `in_flight` while the handler runs, `done` once cached."""

    state: Literal["in_flight", "done"]
    body_hash: str
    response: CachedResponse | None


@runtime_checkable
class IdempotencyStore(Protocol):
    """Dual-layer idempotency port (HTTP cache half).

    Concrete adapters: `RedisIdempotencyStore` for production, `FakeIdempotencyStore`
    for unit tests. The middleware never imports either directly.
    """

    async def claim(self, key: str, body_hash: str, ttl_seconds: int) -> bool:
        """Atomic claim (`SET NX EX`). True iff this caller now owns the key."""

    async def get(self, key: str) -> StoreEntry | None:
        """Read the current entry, or None if the key is absent."""

    async def complete(
        self,
        key: str,
        body_hash: str,
        response: CachedResponse,
        ttl_seconds: int,
    ) -> None:
        """Overwrite the in_flight stub with the final cached response."""
