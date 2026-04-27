"""Contract tests for the error envelope.

FastAPI TestClient with one fake endpoint per error type. Covers
AC-phase1-shared-005-01, -02, -03, -05, -06, -07.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from vaultchain.shared.delivery import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    register_error_handlers,
)
from vaultchain.shared.delivery.error_handlers import DOC_URL_PREFIX
from vaultchain.shared.domain.errors import (
    ConflictError,
    NotFoundError,
    PermissionError,
    ValidationError,
)


class _RequestSchema(BaseModel):
    name: str
    quantity: int


def _build_app() -> FastAPI:
    """A throwaway FastAPI app exercising every handler branch."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    @app.get("/raise/validation")
    async def _raise_validation() -> None:
        raise ValidationError("bad amount", details={"field": "amount"})

    @app.get("/raise/not-found")
    async def _raise_not_found() -> None:
        raise NotFoundError()

    @app.get("/raise/conflict")
    async def _raise_conflict() -> None:
        raise ConflictError(
            details={"current_version": 3, "expected_version": 2},
        )

    @app.get("/raise/permission")
    async def _raise_permission() -> None:
        raise PermissionError()

    @app.get("/raise/boom")
    async def _raise_boom() -> None:
        raise RuntimeError("internal: secret leak attempt")

    @app.post("/echo")
    async def _echo(payload: _RequestSchema) -> dict[str, Any]:
        return {"ok": True, "name": payload.name, "qty": payload.quantity}

    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    # raise_server_exceptions=False so unhandled exceptions hit our handler
    # instead of bubbling up as 500 Test errors with no body.
    with TestClient(_build_app(), raise_server_exceptions=False) as c:
        yield c


def _assert_envelope_shape(body: dict[str, Any]) -> dict[str, Any]:
    assert set(body.keys()) == {"error"}
    err = body["error"]
    assert set(err.keys()) == {
        "code",
        "message",
        "details",
        "request_id",
        "documentation_url",
    }
    assert isinstance(err["details"], dict)
    assert err["request_id"]
    return err


def test_validation_error_returns_400_envelope(client: TestClient) -> None:
    """AC-01, AC-02: ValidationError → 400 with envelope + validation.<sub>."""
    response = client.get("/raise/validation")

    assert response.status_code == 400
    err = _assert_envelope_shape(response.json())
    assert err["code"].startswith("validation.")
    assert err["message"] == "bad amount"
    assert err["details"] == {"field": "amount"}


def test_conflict_error_returns_409_envelope(client: TestClient) -> None:
    """AC-03: ConflictError → 409 with details round-tripped unchanged."""
    response = client.get("/raise/conflict")

    assert response.status_code == 409
    err = _assert_envelope_shape(response.json())
    assert err["code"] == "common.conflict"
    assert err["details"] == {"current_version": 3, "expected_version": 2}


def test_not_found_error_returns_404_envelope(client: TestClient) -> None:
    response = client.get("/raise/not-found")
    assert response.status_code == 404
    err = _assert_envelope_shape(response.json())
    assert err["code"] == "common.not_found"


def test_permission_error_returns_403_envelope(client: TestClient) -> None:
    response = client.get("/raise/permission")
    assert response.status_code == 403
    err = _assert_envelope_shape(response.json())
    assert err["code"] == "common.permission_denied"


def test_unexpected_exception_returns_500_generic_envelope(client: TestClient) -> None:
    """AC-07: unhandled Exception → 500, no internals leaked."""
    response = client.get("/raise/boom")

    assert response.status_code == 500
    err = _assert_envelope_shape(response.json())
    assert err["code"] == "internal.unexpected"
    assert "secret leak" not in err["message"]
    assert "RuntimeError" not in err["message"]
    assert err["request_id"] in err["message"]


def test_pydantic_validation_uses_envelope(client: TestClient) -> None:
    """AC-06: FastAPI's RequestValidationError → custom envelope, not default."""
    response = client.post("/echo", json={"name": 1, "quantity": "x"})

    assert response.status_code == 422
    body = response.json()
    err = _assert_envelope_shape(body)
    assert err["code"] == "validation.request_schema"
    assert "fields" in err["details"]
    assert isinstance(err["details"]["fields"], list)
    # FastAPI's default `{"detail": [...]}` shape MUST NOT coexist.
    assert "detail" not in body


def test_documentation_url_format(client: TestClient) -> None:
    """AC-05: documentation_url is `<prefix>{code}` literal."""
    response = client.get("/raise/conflict")
    err = response.json()["error"]
    assert err["documentation_url"] == f"{DOC_URL_PREFIX}{err['code']}"
    assert err["documentation_url"].startswith("https://docs.vaultchain.example/errors/")


def test_request_id_propagates_to_envelope_and_header(client: TestClient) -> None:
    """AC-04 (delivery slice): error responses also carry request_id."""
    response = client.get(
        "/raise/conflict",
        headers={REQUEST_ID_HEADER: "req_test_envelope"},
    )

    assert response.headers[REQUEST_ID_HEADER] == "req_test_envelope"
    err = response.json()["error"]
    assert err["request_id"] == "req_test_envelope"
