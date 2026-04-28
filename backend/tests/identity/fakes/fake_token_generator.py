"""Deterministic `RefreshTokenGenerator` fake — incrementing counters."""

from __future__ import annotations


class DeterministicTokenGenerator:
    """Each call returns a predictable token derived from a counter.

    Tests can `seed` to reset between cases, or just instantiate fresh.
    """

    def __init__(self) -> None:
        self._access_counter: int = 0
        self._refresh_counter: int = 0
        self._csrf_counter: int = 0

    def generate_access_token(self) -> str:
        self._access_counter += 1
        return f"vc_at_TEST_{self._access_counter:06d}"

    def generate_refresh_token(self) -> str:
        self._refresh_counter += 1
        return f"vc_rt_TEST_{self._refresh_counter:06d}"

    def generate_csrf_token(self) -> str:
        self._csrf_counter += 1
        return f"vc_csrf_TEST_{self._csrf_counter:06d}"
