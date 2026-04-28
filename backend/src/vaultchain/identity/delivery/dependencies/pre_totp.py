"""``get_pre_totp_user`` FastAPI dependency — AC-phase1-identity-005-05.

Reads the ``Authorization: Bearer <pre_totp_token>`` header, hashes
the bearer token (sha256 hex), looks up the cached payload, and
asserts the cached intent matches the route's required intent.

The dependency factory is parameterised by intent so each TOTP route
can declare exactly which gate it expects:

  * ``Depends(get_pre_totp_user(PreTotpIntent.ENROLL))`` for /auth/totp/enroll{,/confirm}
  * ``Depends(get_pre_totp_user(PreTotpIntent.CHALLENGE))`` for /auth/totp/verify

The route handler can also evict the entry after a successful consume —
intent is enforced here, eviction is delivery-layer concern.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Protocol
from uuid import UUID

from vaultchain.identity.domain.errors import PreTotpTokenInvalid
from vaultchain.identity.domain.ports import PreTotpIntent, PreTotpTokenCache
from vaultchain.identity.infra.tokens.hashing import sha256_hex


class _RequestLike(Protocol):
    """Headers-bearing request shape — matches Starlette's ``Request`` and
    bespoke test stubs alike. ``Any`` on the headers attr keeps Starlette's
    `Headers` (case-insensitive multimap) compatible without importing
    Starlette into a domain-adjacent module.
    """

    @property
    def headers(self) -> Any: ...


def _read_bearer(headers: Any) -> str | None:
    for k, v in headers.items():
        if str(k).lower() == "authorization":
            scheme, _, token = str(v).partition(" ")
            if scheme.lower() == "bearer" and token:
                return str(token)
    return None


def make_get_pre_totp_user(
    *,
    cache: PreTotpTokenCache,
    intent: PreTotpIntent,
) -> Callable[[_RequestLike], Coroutine[Any, Any, UUID]]:
    """Build a coroutine dependency that resolves the user_id behind a
    pre-totp bearer token. Intent mismatch raises ``PreTotpTokenInvalid``
    — same code as missing/expired so we don't leak which routes are valid.
    """

    async def get_pre_totp_user(request: _RequestLike) -> UUID:
        bearer = _read_bearer(request.headers)
        if bearer is None:
            raise PreTotpTokenInvalid(details={"reason": "missing_bearer"})
        payload = await cache.get(sha256_hex(bearer))
        if payload is None:
            raise PreTotpTokenInvalid(details={"reason": "unknown_or_expired"})
        if payload.intent is not intent:
            raise PreTotpTokenInvalid(
                details={"reason": "intent_mismatch", "expected": intent.value}
            )
        return payload.user_id

    return get_pre_totp_user


__all__ = ["make_get_pre_totp_user"]
