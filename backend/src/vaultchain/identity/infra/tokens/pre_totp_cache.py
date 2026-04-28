"""Redis-backed `PreTotpTokenCache` — 5-minute TTL between magic-link
verify and the TOTP enrollment / challenge step. AC-phase1-identity-005-05.

Stores ``pre_totp:<sha256(token).hexdigest()>`` → JSON payload with
the user id and intent ("enroll" | "challenge"). Single-use semantics:
the route handler evicts the entry on success.
"""

from __future__ import annotations

import json
from uuid import UUID

import redis.asyncio as aioredis

from vaultchain.identity.domain.ports import (
    PreTotpIntent,
    PreTotpPayload,
    PreTotpTokenCache,
)

#: Redis key prefix; production deployments share Redis across services.
KEY_PREFIX = "pre_totp:"
#: 5-minute TTL per AC-phase1-identity-005-05.
DEFAULT_TTL_SECONDS = 5 * 60


def _serialize(payload: PreTotpPayload) -> str:
    return json.dumps(
        {"user_id": str(payload.user_id), "intent": payload.intent.value},
        separators=(",", ":"),
    )


def _deserialize(raw: bytes | str) -> PreTotpPayload:
    data = json.loads(raw)
    return PreTotpPayload(
        user_id=UUID(data["user_id"]),
        intent=PreTotpIntent(data["intent"]),
    )


class RedisPreTotpTokenCache:
    """Concrete `PreTotpTokenCache` against `redis.asyncio`."""

    def __init__(self, client: aioredis.Redis, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._client = client
        self._ttl = ttl_seconds

    @classmethod
    def from_url(
        cls, url: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS
    ) -> RedisPreTotpTokenCache:
        client: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            url, encoding="utf-8", decode_responses=False
        )
        return cls(client, ttl_seconds=ttl_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def set(self, token_sha256_hex: str, payload: PreTotpPayload) -> None:
        await self._client.set(f"{KEY_PREFIX}{token_sha256_hex}", _serialize(payload), ex=self._ttl)

    async def get(self, token_sha256_hex: str) -> PreTotpPayload | None:
        raw = await self._client.get(f"{KEY_PREFIX}{token_sha256_hex}")
        if raw is None:
            return None
        return _deserialize(raw)

    async def evict(self, token_sha256_hex: str) -> None:
        await self._client.delete(f"{KEY_PREFIX}{token_sha256_hex}")


def _adapter_conforms_to_protocol() -> None:
    cache: PreTotpTokenCache = RedisPreTotpTokenCache(aioredis.Redis())
    _ = cache


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "KEY_PREFIX",
    "RedisPreTotpTokenCache",
]
