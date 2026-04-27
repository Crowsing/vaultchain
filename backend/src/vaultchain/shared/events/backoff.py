"""Exponential backoff math for outbox event redelivery.

Pure function — no side effects, no I/O — to keep AC-phase1-shared-004-07
unit-testable in isolation. Deliberately separated from the worker module
because backoff is fence-post-prone and easier to verify on its own.
"""

from __future__ import annotations

from typing import Final

DEFAULT_BASE_SECONDS: Final[float] = 1.0
DEFAULT_FACTOR: Final[float] = 2.0
DEFAULT_MAX_SECONDS: Final[float] = 60.0


def backoff_seconds(
    attempts: int,
    *,
    base: float = DEFAULT_BASE_SECONDS,
    factor: float = DEFAULT_FACTOR,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> float:
    """`min(base * factor**attempts, max_seconds)`. `attempts == 0` → `base`."""
    if attempts < 0:
        raise ValueError("attempts must be non-negative")
    if base <= 0 or factor <= 0:
        raise ValueError("base and factor must be positive")
    raw = base * (factor**attempts)
    return min(raw, max_seconds)


__all__ = ["DEFAULT_BASE_SECONDS", "DEFAULT_FACTOR", "DEFAULT_MAX_SECONDS", "backoff_seconds"]
