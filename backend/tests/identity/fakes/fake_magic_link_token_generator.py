"""Deterministic ``MagicLinkTokenGenerator`` — emits ``ml-tok-{n}``."""

from __future__ import annotations


class DeterministicMagicLinkTokenGenerator:
    def __init__(self, *, prefix: str = "ml-tok-") -> None:
        self._prefix = prefix
        self._counter = 0

    def generate(self) -> str:
        self._counter += 1
        return f"{self._prefix}{self._counter}"


__all__ = ["DeterministicMagicLinkTokenGenerator"]
