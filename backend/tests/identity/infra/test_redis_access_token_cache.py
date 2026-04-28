"""RedisAccessTokenCache adapter tests — AC-phase1-identity-004-02.

Real Redis via testcontainers; round-trip set/get with TTL, eviction, and
expiry-after-TTL semantics.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from testcontainers.redis import RedisContainer

from vaultchain.identity.domain.ports import AccessTokenCache, CachedAccessToken
from vaultchain.identity.infra.tokens.redis_cache import (
    KEY_PREFIX,
    RedisAccessTokenCache,
)


@pytest.fixture(scope="module")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer("redis:7-alpine") as r:
        yield r


@pytest.fixture(scope="module")
def redis_url(redis_container: RedisContainer) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(redis_container.port)
    return f"redis://{host}:{port}/0"


@pytest_asyncio.fixture
async def cache(redis_url: str) -> AsyncIterator[RedisAccessTokenCache]:
    c = RedisAccessTokenCache.from_url(redis_url, ttl_seconds=900)
    yield c
    await c.aclose()


def _payload(*, expires_in_seconds: int = 600) -> CachedAccessToken:
    return CachedAccessToken(
        user_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
        scopes=("user",),
        session_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_ac_02_set_then_get_round_trips(cache: RedisAccessTokenCache) -> None:
    p = _payload()
    await cache.set("abc123", p)

    out = await cache.get("abc123")
    assert out is not None
    assert out.user_id == p.user_id
    assert out.session_id == p.session_id
    assert out.scopes == p.scopes


@pytest.mark.asyncio
async def test_ac_02_get_returns_none_for_missing_key(cache: RedisAccessTokenCache) -> None:
    out = await cache.get("nonexistent-key")
    assert out is None


@pytest.mark.asyncio
async def test_ac_02_evict_removes_key(cache: RedisAccessTokenCache) -> None:
    p = _payload()
    await cache.set("evict-me", p)
    assert await cache.get("evict-me") is not None
    await cache.evict("evict-me")
    assert await cache.get("evict-me") is None


@pytest.mark.asyncio
async def test_ac_02_ttl_expires_entry(redis_url: str) -> None:
    """Use a 1-second cap so we can poll expiry without making the suite slow."""
    cache = RedisAccessTokenCache.from_url(redis_url, ttl_seconds=1)
    try:
        # expires_at far in the future, but the cache caps to ttl_seconds=1.
        p = _payload(expires_in_seconds=3600)
        await cache.set("ttl-key", p)
        assert await cache.get("ttl-key") is not None
        await asyncio.sleep(1.5)
        assert await cache.get("ttl-key") is None
    finally:
        await cache.aclose()


@pytest.mark.asyncio
async def test_redis_key_uses_at_prefix(cache: RedisAccessTokenCache, redis_url: str) -> None:
    """Reaching past the adapter to confirm the on-disk shape."""
    p = _payload()
    await cache.set("shape-test", p)
    raw_client: aioredis.Redis = aioredis.from_url(redis_url, decode_responses=False)  # type: ignore[no-untyped-call]
    try:
        keys = await raw_client.keys(f"{KEY_PREFIX}*")
        assert any(k == f"{KEY_PREFIX}shape-test".encode() for k in keys)
    finally:
        await raw_client.aclose()


def test_protocol_conformance() -> None:
    cache = RedisAccessTokenCache(aioredis.Redis())  # type: ignore[no-untyped-call]
    assert isinstance(cache, AccessTokenCache)
