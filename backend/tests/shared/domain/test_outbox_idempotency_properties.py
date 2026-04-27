"""Hypothesis: replays on a single (event_id, handler_name) run handler at most once."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


class _IdempotencyShim:
    """Models the `event_handler_log` ON CONFLICT DO NOTHING behavior in memory."""

    def __init__(self) -> None:
        self._claimed: set[tuple[UUID, str]] = set()
        self.invocations: dict[tuple[UUID, str], int] = defaultdict(int)

    def deliver(self, event_id: UUID, handler_name: str) -> bool:
        key = (event_id, handler_name)
        if key in self._claimed:
            return False
        self._claimed.add(key)
        self.invocations[key] += 1
        return True


@pytest.mark.property
@settings(max_examples=200, deadline=1000)
@given(
    event_id=st.uuids(),
    handler_name=st.text(min_size=1, max_size=64),
    redeliveries=st.integers(min_value=1, max_value=10),
)
def test_handler_invocation_at_most_once(
    event_id: UUID, handler_name: str, redeliveries: int
) -> None:
    """Property: any number of redelivery attempts → handler runs at most once."""
    shim = _IdempotencyShim()
    deliveries = [shim.deliver(event_id, handler_name) for _ in range(redeliveries)]
    successes = sum(1 for d in deliveries if d)
    assert successes == 1, f"handler must run exactly once, got {successes}"
    assert shim.invocations[(event_id, handler_name)] == 1
