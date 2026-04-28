"""bcrypt-backed PasswordHasher adapter — phase1-admin-002a.

Cost 12 per AC-phase1-admin-002a-06 — ~250ms verify on a typical
container, deliberate latency floor for the admin login path.
"""

from __future__ import annotations

import bcrypt


class BcryptPasswordHasher:
    """Hashes admin passwords with bcrypt; cost is fixed at construction."""

    def __init__(self, *, cost: int = 12) -> None:
        self._cost = cost

    def hash(self, password: str) -> str:
        salt = bcrypt.gensalt(rounds=self._cost)
        digest = bcrypt.hashpw(password.encode("utf-8"), salt)
        return digest.decode("utf-8")

    def verify(self, password: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except (ValueError, TypeError):
            # Malformed hash bytes — treat as a verification miss; never raise
            # so a corrupted DB row doesn't 500 the login route.
            return False


__all__ = ["BcryptPasswordHasher"]
