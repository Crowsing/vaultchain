"""Hypothesis-driven replay property test (architecture Section 5 must-have #7).

Property: for any command and any sequence of N replays of the same idempotency
key with the same body, the cached response is byte-identical and the handler
is invoked exactly once.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from hypothesis import given, settings
from hypothesis import strategies as st

from vaultchain.shared.delivery.error_handlers import register_error_handlers
from vaultchain.shared.delivery.idempotency import IdempotencyMiddleware
from vaultchain.shared.delivery.middleware import RequestIdMiddleware
from vaultchain.shared.infra.idempotency import FakeIdempotencyStore


def _make_app(store: FakeIdempotencyStore, hit_counter: list[int]) -> FastAPI:
    app = FastAPI()

    @app.post("/cmd")
    async def cmd(request: Request) -> dict[str, Any]:
        hit_counter.append(1)
        body = await request.body()
        return {"echo_len": len(body), "hits": len(hit_counter)}

    app.add_middleware(IdempotencyMiddleware, store=store)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    return app


@pytest.mark.property
@settings(max_examples=50, deadline=2000)
@given(
    body=st.binary(min_size=0, max_size=4096),
    replays=st.integers(min_value=2, max_value=6),
    key_suffix=st.text(
        alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=4, max_size=64
    ),
)
@pytest.mark.asyncio
async def test_replay_is_byte_identical_and_handler_runs_once(
    body: bytes, replays: int, key_suffix: str
) -> None:
    store = FakeIdempotencyStore()
    hits: list[int] = []
    app = _make_app(store, hits)
    headers = {"Idempotency-Key": f"prop-{key_suffix}", "content-type": "application/octet-stream"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        responses = []
        for _ in range(replays):
            responses.append(await c.post("/cmd", content=body, headers=headers))

    first = responses[0]
    for r in responses[1:]:
        assert r.status_code == first.status_code
        assert r.content == first.content
    assert len(hits) == 1, f"handler should run once, ran {len(hits)} times"
