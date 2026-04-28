"""In-memory `PasswordHasher` fake.

Hash format is the literal ``"fake$<password>"`` so:
- ``hash(p) == hash(p)`` deterministically
- ``verify(p, hash(p)) is True``
- ``verify(p1, hash(p2)) is False`` for ``p1 != p2``

The roundtrip property test (`tests/identity/domain/
test_password_hasher_properties.py`) drives both this fake and the real
`BcryptPasswordHasher` adapter to enforce the contract.
"""

from __future__ import annotations


class FakePasswordHasher:
    """No-op hasher with the same shape as the production port."""

    PREFIX = "fake$"

    def hash(self, password: str) -> str:
        return f"{self.PREFIX}{password}"

    def verify(self, password: str, hashed: str) -> bool:
        if not hashed.startswith(self.PREFIX):
            return False
        return hashed[len(self.PREFIX) :] == password


__all__ = ["FakePasswordHasher"]
