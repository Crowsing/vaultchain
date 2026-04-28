"""Deterministic `BackupCodeService` fake — no argon2 dependency.

Generates a fixed, predictable list (so tests can assert exact codes)
and uses an identity-style "hash" with a sentinel prefix so the
hash/verify flow can be exercised without real cryptography.
"""

from __future__ import annotations


class FakeBackupCodeService:
    SENTINEL = b"hash:"

    def __init__(self) -> None:
        # Stable across runs so tests can match exact ciphertext.
        self._next: list[str] = [f"BC{i:02d}-CODE{i:02d}" for i in range(10)]

    def generate(self, count: int = 10) -> list[str]:
        return list(self._next[:count])

    def hash(self, code: str) -> bytes:
        return self.SENTINEL + code.encode("ascii")

    def find_matching_hash(self, code: str, hashes: list[bytes]) -> bytes | None:
        target = self.hash(code)
        for h in hashes:
            if h == target:
                return h
        return None
