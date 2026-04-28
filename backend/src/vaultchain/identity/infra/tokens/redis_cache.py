"""Redis-backed `AccessTokenCache` adapter — `SET EX` for TTL.

Stores `at:<sha256(token).hexdigest()>` → JSON of the cached payload, with
TTL matching the access-token lifetime (15 minutes per architecture
Section 4). The hex digest is the binding key — never the raw token.

A secondary key ``session:<session_id>`` points to the current access-
token hex digest so revocation can find and evict the access-token
entry without holding the raw token.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import redis.asyncio as aioredis

from vaultchain.identity.domain.ports import AccessTokenCache, CachedAccessToken

#: Redis key prefix; production deployments share Redis across services.
KEY_PREFIX = "at:"
#: Secondary index — session id → current access-token sha256 hex digest.
SESSION_INDEX_PREFIX = "session:"

#: 15-minute access-token TTL per architecture Section 4.
DEFAULT_TTL_SECONDS = 15 * 60


def _serialize(payload: CachedAccessToken) -> str:
    return json.dumps(
        {
            "user_id": str(payload.user_id),
            "expires_at": payload.expires_at.isoformat(),
            "scopes": list(payload.scopes),
            "session_id": str(payload.session_id),
        },
        separators=(",", ":"),
    )


def _deserialize(raw: bytes | str) -> CachedAccessToken:
    data = json.loads(raw)
    return CachedAccessToken(
        user_id=UUID(data["user_id"]),
        expires_at=datetime.fromisoformat(data["expires_at"]),
        scopes=tuple(data["scopes"]),
        session_id=UUID(data["session_id"]),
    )


class RedisAccessTokenCache:
    """Concrete `AccessTokenCache` against `redis.asyncio`."""

    def __init__(self, client: aioredis.Redis, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._client = client
        self._ttl = ttl_seconds

    @classmethod
    def from_url(cls, url: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> RedisAccessTokenCache:
        client: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            url, encoding="utf-8", decode_responses=False
        )
        return cls(client, ttl_seconds=ttl_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def set(self, token_sha256_hex: str, payload: CachedAccessToken) -> None:
        ttl = max(int((payload.expires_at - datetime.now(UTC)).total_seconds()), 1)
        # Cap to the configured TTL so a misuse ever-so-far in the future
        # doesn't keep the entry alive past the access-token lifetime.
        ttl = min(ttl, self._ttl)
        await self._client.set(f"{KEY_PREFIX}{token_sha256_hex}", _serialize(payload), ex=ttl)
        # Maintain the session index so RevokeSession can evict immediately
        # without the route handler holding the raw access token.
        await self._client.set(
            f"{SESSION_INDEX_PREFIX}{payload.session_id}", token_sha256_hex, ex=ttl
        )

    async def get(self, token_sha256_hex: str) -> CachedAccessToken | None:
        raw = await self._client.get(f"{KEY_PREFIX}{token_sha256_hex}")
        if raw is None:
            return None
        return _deserialize(raw)

    async def evict(self, token_sha256_hex: str) -> None:
        await self._client.delete(f"{KEY_PREFIX}{token_sha256_hex}")

    async def evict_by_session(self, session_id: UUID) -> None:
        idx_key = f"{SESSION_INDEX_PREFIX}{session_id}"
        token_hex_raw = await self._client.get(idx_key)
        if token_hex_raw is not None:
            token_hex = (
                token_hex_raw.decode("ascii") if isinstance(token_hex_raw, bytes) else token_hex_raw
            )
            await self._client.delete(f"{KEY_PREFIX}{token_hex}")
        await self._client.delete(idx_key)


# Cheap structural confirmation that the adapter satisfies the port without
# requiring a Redis instance at import time. Useful for type-checkers and
# the orm/ports smoke test.
def _adapter_conforms_to_protocol() -> None:
    cache: AccessTokenCache = RedisAccessTokenCache(aioredis.Redis())
    _ = cache  # touch to silence unused warning


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "KEY_PREFIX",
    "SESSION_INDEX_PREFIX",
    "RedisAccessTokenCache",
]
