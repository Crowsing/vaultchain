"""IdempotencyMiddleware behavior tests (AC-phase1-shared-006-01..07)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request

from vaultchain.shared.delivery.error_handlers import register_error_handlers
from vaultchain.shared.delivery.idempotency import IdempotencyMiddleware
from vaultchain.shared.delivery.middleware import RequestIdMiddleware
from vaultchain.shared.domain.ports import IdempotencyStore
from vaultchain.shared.infra.idempotency import FakeIdempotencyStore


def _build_app(store: IdempotencyStore, *, hit_counter: list[int] | None = None) -> FastAPI:
    """Tiny app with one POST + one GET that exercise the middleware."""
    counter = hit_counter if hit_counter is not None else []
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, Any]:
        counter.append(1)
        body = await request.json()
        return {"got": body, "hit_count": len(counter)}

    @app.post("/boom")
    async def boom(request: Request) -> dict[str, Any]:
        counter.append(1)
        raise RuntimeError("kaboom")

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        counter.append(1)
        return {"pong": "ok"}

    # Order matters: RequestId outermost, then Idempotency, then error handlers.
    app.add_middleware(IdempotencyMiddleware, store=store)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    return app


async def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_first_request_claims_and_proceeds() -> None:
    """AC-01: first request with key claims SET NX and runs the handler."""
    store = FakeIdempotencyStore()
    hits: list[int] = []
    app = _build_app(store, hit_counter=hits)
    async with await _client(app) as c:
        resp = await c.post("/echo", json={"a": 1}, headers={"Idempotency-Key": "k1"})
    assert resp.status_code == 200
    assert resp.json()["got"] == {"a": 1}
    assert len(hits) == 1
    assert len(store._data) == 1


@pytest.mark.asyncio
async def test_replay_same_body_returns_cached() -> None:
    """AC-02: same key + same body → cached response, handler not re-invoked."""
    store = FakeIdempotencyStore()
    hits: list[int] = []
    app = _build_app(store, hit_counter=hits)
    async with await _client(app) as c:
        first = await c.post("/echo", json={"x": 42}, headers={"Idempotency-Key": "k2"})
        second = await c.post("/echo", json={"x": 42}, headers={"Idempotency-Key": "k2"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content
    assert len(hits) == 1, "handler must run exactly once"


@pytest.mark.asyncio
async def test_replay_different_body_returns_422() -> None:
    """AC-03: same key + different body → 422 idempotency.conflict_body_mismatch."""
    store = FakeIdempotencyStore()
    app = _build_app(store)
    async with await _client(app) as c:
        await c.post("/echo", json={"x": 1}, headers={"Idempotency-Key": "k3"})
        resp = await c.post("/echo", json={"x": 2}, headers={"Idempotency-Key": "k3"})
    assert resp.status_code == 422
    payload = resp.json()
    assert payload["error"]["code"] == "idempotency.conflict_body_mismatch"
    assert "original_body_hash" in payload["error"]["details"]
    assert "actual_body_hash" in payload["error"]["details"]
    assert (
        payload["error"]["details"]["original_body_hash"]
        != payload["error"]["details"]["actual_body_hash"]
    )


@pytest.mark.asyncio
async def test_handler_500_response_cached() -> None:
    """AC-04: handler exception → 500 envelope cached, retry returns identical."""
    store = FakeIdempotencyStore()
    hits: list[int] = []
    app = _build_app(store, hit_counter=hits)
    async with await _client(app) as c:
        first = await c.post("/boom", json={}, headers={"Idempotency-Key": "k4"})
        second = await c.post("/boom", json={}, headers={"Idempotency-Key": "k4"})
    assert first.status_code == 500
    assert second.status_code == 500
    assert first.content == second.content
    assert len(hits) == 1, "handler runs once even on error"


@pytest.mark.asyncio
async def test_redis_outage_fails_open() -> None:
    """AC-05: store unavailable → fail-open, X-Idempotency-Disabled set, handler runs."""
    store = FakeIdempotencyStore(unavailable=True)
    hits: list[int] = []
    app = _build_app(store, hit_counter=hits)
    async with await _client(app) as c:
        resp = await c.post("/echo", json={"a": 1}, headers={"Idempotency-Key": "k5"})
    assert resp.status_code == 200
    assert resp.headers.get("x-idempotency-disabled") == "1"
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_get_request_unaffected() -> None:
    """AC-06: GET bypasses middleware entirely."""
    store = FakeIdempotencyStore()
    app = _build_app(store)
    async with await _client(app) as c:
        resp = await c.get("/ping", headers={"Idempotency-Key": "k6"})
    assert resp.status_code == 200
    assert resp.json() == {"pong": "ok"}
    assert len(store._data) == 0


@pytest.mark.asyncio
async def test_no_header_proceeds_unchanged() -> None:
    """AC-07: POST without `Idempotency-Key` flows through without store interaction."""
    store = FakeIdempotencyStore()
    hits: list[int] = []
    app = _build_app(store, hit_counter=hits)
    async with await _client(app) as c:
        resp = await c.post("/echo", json={"a": 1})
    assert resp.status_code == 200
    assert len(store._data) == 0
    assert len(hits) == 1


@pytest.mark.asyncio
async def test_key_too_long_rejected() -> None:
    """Out-of-scope clarification: keys >200 chars → 422 validation.idempotency_key_too_long."""
    store = FakeIdempotencyStore()
    app = _build_app(store)
    long_key = "x" * 201
    async with await _client(app) as c:
        resp = await c.post("/echo", json={"a": 1}, headers={"Idempotency-Key": long_key})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation.idempotency_key_too_long"


@pytest.mark.asyncio
async def test_concurrent_in_flight_returns_409() -> None:
    """AC-08-style: while a key is in-flight, a parallel arrival gets 409 in_flight."""
    store = FakeIdempotencyStore()
    # Simulate that the key is already claimed (in_flight) — without actually running a handler.
    await store.claim("idempotency:127.0.0.1:/echo:dup", body_hash="deadbeef", ttl_seconds=86400)
    app = _build_app(store)
    async with await _client(app) as c:
        # Use a body whose hash matches (to ensure 409 wins over mismatch path).
        resp = await c.post(
            "/echo",
            content=b"",  # empty body → known hash
            headers={"Idempotency-Key": "dup"},
        )
    # The fake's pre-claim used "deadbeef" hash, ours will not match — but in_flight wins
    # before body-hash check (same as Stripe semantics).
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "idempotency.in_flight"


@pytest.mark.asyncio
async def test_response_set_cookie_stripped_from_cache() -> None:
    """Implementation Notes: never cache Set-Cookie / WWW-Authenticate."""
    store = FakeIdempotencyStore()
    app = FastAPI()

    @app.post("/with-cookie")
    async def with_cookie() -> Any:
        from fastapi.responses import JSONResponse

        resp = JSONResponse({"ok": True})
        resp.set_cookie("session", "secret-session-id")
        resp.headers["WWW-Authenticate"] = "Bearer"
        return resp

    app.add_middleware(IdempotencyMiddleware, store=store)
    register_error_handlers(app)

    async with await _client(app) as c:
        first = await c.post("/with-cookie", json={}, headers={"Idempotency-Key": "kcookie"})
        second = await c.post("/with-cookie", json={}, headers={"Idempotency-Key": "kcookie"})

    assert first.status_code == 200
    assert second.status_code == 200
    # First response carries Set-Cookie (set by handler), second (cached) must NOT.
    assert "set-cookie" in {k.lower() for k in first.headers}
    assert "set-cookie" not in {k.lower() for k in second.headers}
    assert "www-authenticate" not in {k.lower() for k in second.headers}


@pytest.mark.asyncio
async def test_concurrent_requests_handler_runs_once() -> None:
    """Two parallel POSTs same key → exactly one handler invocation, one wins, one 409."""
    store = FakeIdempotencyStore(slow_complete=True)
    hits: list[int] = []
    app = _build_app(store, hit_counter=hits)
    async with await _client(app) as c:
        a, b = await asyncio.gather(
            c.post("/echo", json={"x": 1}, headers={"Idempotency-Key": "kc"}),
            c.post("/echo", json={"x": 1}, headers={"Idempotency-Key": "kc"}),
        )
    statuses = sorted([a.status_code, b.status_code])
    assert statuses == [200, 409], f"expected one 200 and one 409, got {statuses}"
    assert len(hits) == 1
