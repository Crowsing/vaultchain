"""Idempotency-store adapters: Redis (prod) + in-memory fake (tests).

Both adapters implement `vaultchain.shared.domain.ports.IdempotencyStore`. The
middleware lives in `delivery/idempotency.py` and depends only on the Protocol.
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import asdict
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from vaultchain.shared.domain.ports import CachedResponse, StoreEntry


class StoreUnavailable(Exception):
    """Raised by adapters when the underlying store is unreachable.

    Middleware catches this to fail-open (per AC-phase1-shared-006-05).
    """


def _entry_to_json(entry: StoreEntry) -> str:
    payload: dict[str, Any] = {"state": entry.state, "body_hash": entry.body_hash}
    if entry.response is not None:
        payload["response"] = {
            "status_code": entry.response.status_code,
            "headers": entry.response.headers,
            "body_b64": base64.b64encode(entry.response.body).decode("ascii"),
        }
    return json.dumps(payload, separators=(",", ":"))


def _entry_from_json(raw: str | bytes) -> StoreEntry:
    data = json.loads(raw)
    response: CachedResponse | None = None
    if "response" in data:
        r = data["response"]
        response = CachedResponse(
            status_code=int(r["status_code"]),
            headers=[tuple(pair) for pair in r["headers"]],
            body=base64.b64decode(r["body_b64"]),
        )
    return StoreEntry(state=data["state"], body_hash=data["body_hash"], response=response)


class FakeIdempotencyStore:
    """In-memory store for unit tests. Mimics Redis SET-NX semantics on a dict.

    Optional knobs:
    - `unavailable=True` → every call raises StoreUnavailable (simulates outage).
    - `slow_complete=True` → `complete()` yields the event loop to provoke
       a deterministic interleaving of two concurrent claims.
    """

    def __init__(self, *, unavailable: bool = False, slow_complete: bool = False) -> None:
        self._data: dict[str, StoreEntry] = {}
        self._unavailable = unavailable
        self._slow_complete = slow_complete
        self._lock = asyncio.Lock()

    async def claim(self, key: str, body_hash: str, ttl_seconds: int) -> bool:
        if self._unavailable:
            raise StoreUnavailable("fake store marked unavailable")
        async with self._lock:
            if key in self._data:
                return False
            self._data[key] = StoreEntry(state="in_flight", body_hash=body_hash, response=None)
            return True

    async def get(self, key: str) -> StoreEntry | None:
        if self._unavailable:
            raise StoreUnavailable("fake store marked unavailable")
        return self._data.get(key)

    async def complete(
        self, key: str, body_hash: str, response: CachedResponse, ttl_seconds: int
    ) -> None:
        if self._unavailable:
            raise StoreUnavailable("fake store marked unavailable")
        if self._slow_complete:
            await asyncio.sleep(0.05)
        self._data[key] = StoreEntry(state="done", body_hash=body_hash, response=response)


class RedisIdempotencyStore:
    """Redis-backed adapter — `SET NX EX` for claim, plain `SET EX` for complete."""

    def __init__(self, client: aioredis.Redis) -> None:
        self._client = client

    @classmethod
    def from_url(cls, url: str) -> RedisIdempotencyStore:
        client: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            url, encoding="utf-8", decode_responses=False
        )
        return cls(client)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def claim(self, key: str, body_hash: str, ttl_seconds: int) -> bool:
        entry = StoreEntry(state="in_flight", body_hash=body_hash, response=None)
        try:
            result = await self._client.set(key, _entry_to_json(entry), nx=True, ex=ttl_seconds)
        except RedisError as exc:
            raise StoreUnavailable(str(exc)) from exc
        return bool(result)

    async def get(self, key: str) -> StoreEntry | None:
        try:
            raw = await self._client.get(key)
        except RedisError as exc:
            raise StoreUnavailable(str(exc)) from exc
        if raw is None:
            return None
        return _entry_from_json(raw)

    async def complete(
        self, key: str, body_hash: str, response: CachedResponse, ttl_seconds: int
    ) -> None:
        entry = StoreEntry(state="done", body_hash=body_hash, response=response)
        try:
            await self._client.set(key, _entry_to_json(entry), ex=ttl_seconds)
        except RedisError as exc:
            raise StoreUnavailable(str(exc)) from exc


# `asdict` is imported above for symmetry with future `StoreEntry.to_dict()` helpers
# (avoid an unused-import warning if linters get strict).
_ = asdict
