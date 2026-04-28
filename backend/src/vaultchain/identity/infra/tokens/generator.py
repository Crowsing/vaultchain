"""Secrets-backed `RefreshTokenGenerator` adapter.

Tokens are URL-safe base64-encoded 32-byte random strings, prefixed with
``vc_at_`` / ``vc_rt_`` / ``vc_csrf_`` so they're greppable in logs without
exposing the entropy material. Per the brief Implementation Notes.
"""

from __future__ import annotations

import secrets

ACCESS_TOKEN_PREFIX = "vc_at_"  # noqa: S105 — log-greppable prefix, not a secret
REFRESH_TOKEN_PREFIX = "vc_rt_"  # noqa: S105 — log-greppable prefix, not a secret
CSRF_TOKEN_PREFIX = "vc_csrf_"  # noqa: S105 — log-greppable prefix, not a secret
TOKEN_RANDOM_BYTES = 32


def _random() -> str:
    return secrets.token_urlsafe(TOKEN_RANDOM_BYTES)


class SecretsRefreshTokenGenerator:
    """Production adapter on top of :mod:`secrets`."""

    def generate_access_token(self) -> str:
        return f"{ACCESS_TOKEN_PREFIX}{_random()}"

    def generate_refresh_token(self) -> str:
        return f"{REFRESH_TOKEN_PREFIX}{_random()}"

    def generate_csrf_token(self) -> str:
        return f"{CSRF_TOKEN_PREFIX}{_random()}"


__all__ = [
    "ACCESS_TOKEN_PREFIX",
    "CSRF_TOKEN_PREFIX",
    "REFRESH_TOKEN_PREFIX",
    "SecretsRefreshTokenGenerator",
]
