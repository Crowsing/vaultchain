"""Real-Redis adapter tests for `RedisIdempotencyStore` (AC-phase1-shared-006-08)."""

from __future__ import annotations

import asyncio

import pytest
from testcontainers.redis import RedisContainer

from vaultchain.shared.domain.ports import CachedResponse
from vaultchain.shared.infra.idempotency import RedisIdempotencyStore


@pytest.fixture(scope="module")
def redis_url() -> object:
    """Spawn a real Redis instance via testcontainers; yield its URL."""
    with RedisContainer("redis:7-alpine") as redis:
        host = redis.get_container_host_ip()
        port = redis.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.mark.asyncio
async def test_set_nx_real_redis(redis_url: str) -> None:
    """First claim succeeds; same-key second claim returns False."""
    store = RedisIdempotencyStore.from_url(redis_url)
    try:
        first = await store.claim("test:nx:1", body_hash="abc", ttl_seconds=60)
        second = await store.claim("test:nx:1", body_hash="abc", ttl_seconds=60)
        assert first is True
        assert second is False
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_concurrent_claim_exactly_one_wins(redis_url: str) -> None:
    """50 parallel claims on the same key — exactly one True, rest False."""
    store = RedisIdempotencyStore.from_url(redis_url)
    try:
        results = await asyncio.gather(
            *(store.claim("test:race:1", body_hash="zz", ttl_seconds=60) for _ in range(50))
        )
        assert sum(results) == 1
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_ttl_expires_key(redis_url: str) -> None:
    """Short TTL: after expiry the key is gone, so a fresh claim succeeds."""
    store = RedisIdempotencyStore.from_url(redis_url)
    try:
        ok1 = await store.claim("test:ttl:1", body_hash="aa", ttl_seconds=1)
        assert ok1 is True
        # Wait past TTL.
        await asyncio.sleep(1.5)
        ok2 = await store.claim("test:ttl:1", body_hash="aa", ttl_seconds=60)
        assert ok2 is True
    finally:
        await store.aclose()


@pytest.mark.asyncio
async def test_complete_overwrites_in_flight(redis_url: str) -> None:
    """Once `complete()` is called, `get()` returns the cached response, not the in_flight stub."""
    store = RedisIdempotencyStore.from_url(redis_url)
    try:
        await store.claim("test:complete:1", body_hash="aa", ttl_seconds=60)
        cached = CachedResponse(
            status_code=200, headers=[("content-type", "application/json")], body=b'{"ok":true}'
        )
        await store.complete("test:complete:1", body_hash="aa", response=cached, ttl_seconds=60)
        entry = await store.get("test:complete:1")
        assert entry is not None
        assert entry.state == "done"
        assert entry.response is not None
        assert entry.response.body == b'{"ok":true}'
    finally:
        await store.aclose()
