"""Hashing helpers for session tokens.

The ``refresh_token_hash`` column on ``identity.sessions`` is a deterministic
sha256 of the raw refresh token. Refresh tokens are 32 bytes of cryptographic
randomness, so sha256 is sufficient — argon2id is only needed for low-entropy
inputs (e.g. backup codes / passwords). Lookup must be O(1) on every refresh,
which argon2id (slow + salted) cannot satisfy.

The Redis access-token cache key is ``at:<sha256(token).hexdigest()>``.
"""

from __future__ import annotations

import hashlib


def sha256_bytes(token_raw: str) -> bytes:
    """Binary digest — what the database column stores."""
    return hashlib.sha256(token_raw.encode("ascii")).digest()


def sha256_hex(token_raw: str) -> str:
    """Hex digest — what the cache key uses."""
    return hashlib.sha256(token_raw.encode("ascii")).hexdigest()


__all__ = ["sha256_bytes", "sha256_hex"]
