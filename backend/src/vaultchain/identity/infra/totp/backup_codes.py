"""argon2id-backed `BackupCodeService`.

Generates 10 codes in the ``XXXX-XXXX`` format (8 alphanum chars,
uppercase, hyphen-delimited per the brief), hashes via argon2id,
and verifies a plaintext against a list of stored hashes. The
"find_matching_hash" helper returns the matching ciphertext so the
caller can remove it from the user's stored list (one-time use,
AC-phase1-identity-003-08).
"""

from __future__ import annotations

import secrets
import string

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

#: Excludes I/O/0/1 to keep codes unambiguous when read aloud.
_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "IO01")
_GROUP_LEN = 4
_GROUP_COUNT = 2


def _make_code() -> str:
    groups = [
        "".join(secrets.choice(_ALPHABET) for _ in range(_GROUP_LEN)) for _ in range(_GROUP_COUNT)
    ]
    return "-".join(groups)


class Argon2BackupCodeService:
    """Concrete `BackupCodeService` using `argon2-cffi`."""

    def __init__(self, *, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()

    def generate(self, count: int = 10) -> list[str]:
        return [_make_code() for _ in range(count)]

    def hash(self, code: str) -> bytes:
        return self._hasher.hash(code).encode("ascii")

    def find_matching_hash(self, code: str, hashes: list[bytes]) -> bytes | None:
        for h in hashes:
            try:
                if self._hasher.verify(h.decode("ascii"), code):
                    return h
            except VerifyMismatchError:
                continue
        return None


__all__ = ["Argon2BackupCodeService"]
