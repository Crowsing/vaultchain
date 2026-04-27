"""Application-layer tests for the request-id middleware.

Covers AC-phase1-shared-005-04: an incoming `X-Request-ID` header is honoured;
when absent, the middleware mints a `req_…` token, exposes it via the
contextvar (consumed by the error handlers), and writes it back on the
response header.
"""

from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from vaultchain.shared.delivery import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    get_request_id,
)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/probe")
    async def probe() -> dict[str, str | None]:
        # Exercises the contextvar from inside a handler, not just the header.
        return {"request_id": get_request_id()}

    return app


def test_request_id_from_header_passes_through() -> None:
    """AC-04: client-supplied header survives unchanged on response + body."""
    app = _build_app()
    client = TestClient(app)

    response = client.get("/probe", headers={REQUEST_ID_HEADER: "req_test_provided"})

    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "req_test_provided"
    assert response.json() == {"request_id": "req_test_provided"}


def test_request_id_generated_when_missing() -> None:
    """AC-04: middleware mints a `req_<hex>` id when the header is absent."""
    app = _build_app()
    client = TestClient(app)

    response = client.get("/probe")

    assert response.status_code == 200
    generated = response.headers[REQUEST_ID_HEADER]
    assert re.match(r"^req_[0-9a-f]{32}$", generated), generated
    assert response.json() == {"request_id": generated}


def test_request_id_unbinds_after_request() -> None:
    """ContextVar must reset between requests — no leakage between tasks."""
    app = _build_app()
    client = TestClient(app)

    client.get("/probe", headers={REQUEST_ID_HEADER: "req_first"})
    # Outside any request: the ContextVar default re-asserts.
    assert get_request_id() is None
