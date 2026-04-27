"""Domain Protocol shape for `IdempotencyStore` (AC-phase1-shared-006-01)."""

from __future__ import annotations

import inspect
from typing import Protocol, get_type_hints, runtime_checkable

import pytest


def test_idempotency_store_is_a_protocol() -> None:
    from vaultchain.shared.domain.ports import IdempotencyStore

    assert issubclass(IdempotencyStore, Protocol)  # type: ignore[arg-type]


def test_idempotency_store_protocol_signatures() -> None:
    """Three async methods: claim / get / complete with the documented shape."""
    from vaultchain.shared.domain.ports import IdempotencyStore, StoreEntry

    expected = {
        "claim": ["self", "key", "body_hash", "ttl_seconds"],
        "get": ["self", "key"],
        "complete": ["self", "key", "body_hash", "response", "ttl_seconds"],
    }
    for name, params in expected.items():
        method = getattr(IdempotencyStore, name)
        assert inspect.iscoroutinefunction(method), f"{name} must be async"
        sig = inspect.signature(method)
        assert (
            list(sig.parameters) == params
        ), f"{name} expected params {params}, got {list(sig.parameters)}"

    hints = get_type_hints(IdempotencyStore.claim)
    assert hints["return"] is bool, "claim must return bool"

    get_hints = get_type_hints(IdempotencyStore.get)
    # Optional[StoreEntry] resolves to StoreEntry | None
    assert get_hints["return"] == StoreEntry | None  # type: ignore[comparison-overlap]


def test_store_entry_dataclass_shape() -> None:
    """`StoreEntry` carries state, body_hash, and an optional cached response."""
    from vaultchain.shared.domain.ports import CachedResponse, StoreEntry

    in_flight = StoreEntry(state="in_flight", body_hash="abc", response=None)
    assert in_flight.state == "in_flight"
    assert in_flight.response is None

    done = StoreEntry(
        state="done",
        body_hash="abc",
        response=CachedResponse(
            status_code=201,
            headers=[("content-type", "application/json")],
            body=b"{}",
        ),
    )
    assert done.state == "done"
    assert done.response is not None
    assert done.response.status_code == 201


def test_protocol_is_runtime_checkable() -> None:
    """A duck-typed implementation satisfies isinstance() check at runtime."""
    from vaultchain.shared.domain.ports import IdempotencyStore

    # If it isn't @runtime_checkable, isinstance raises TypeError.
    with pytest.MonkeyPatch.context() as _:
        # Build a minimal duck-type shim.
        class _Shim:
            async def claim(self, key: str, body_hash: str, ttl_seconds: int) -> bool:
                return True

            async def get(self, key: str) -> object:
                return None

            async def complete(
                self, key: str, body_hash: str, response: object, ttl_seconds: int
            ) -> None:
                return None

        # Will raise TypeError if Protocol is not @runtime_checkable.
        assert isinstance(_Shim(), IdempotencyStore)


@runtime_checkable
class _MarkerProto(Protocol):
    pass
