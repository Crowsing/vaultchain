"""Pure-function backoff math — exhaustive (architecture Section 5)."""

from __future__ import annotations

import pytest

from vaultchain.shared.events.backoff import backoff_seconds


@pytest.mark.parametrize(
    ("attempts", "expected"),
    [
        (0, 1.0),
        (1, 2.0),
        (2, 4.0),
        (3, 8.0),
        (4, 16.0),
        (5, 32.0),
        (6, 60.0),  # capped at max_seconds=60
        (10, 60.0),
        (100, 60.0),
    ],
)
def test_backoff_default_curve(attempts: int, expected: float) -> None:
    assert backoff_seconds(attempts) == expected


def test_backoff_rejects_negative_attempts() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        backoff_seconds(-1)


def test_backoff_rejects_non_positive_base() -> None:
    with pytest.raises(ValueError, match="positive"):
        backoff_seconds(0, base=0.0)


def test_backoff_custom_curve() -> None:
    assert backoff_seconds(2, base=2.0, factor=3.0, max_seconds=120.0) == 18.0
