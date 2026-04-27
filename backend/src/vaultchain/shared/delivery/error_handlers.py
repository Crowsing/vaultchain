"""FastAPI exception handlers — translate domain/runtime errors into the canonical envelope.

Wired by `register_error_handlers(app)` from the composition root.
Order matters: register `DomainError` last so subclasses match their concrete
type first. FastAPI's exception_handler resolution scans handlers in
registration order; the most-specific handler wins.

The envelope shape is fixed by architecture-decisions Section 4 and the
`ErrorEnvelope` Pydantic model below; every 4xx/5xx response from the app
returns the same shape. Stack traces, ORM strings, and inputs are NEVER
included on 5xx — the user-facing 500 message is generic and a Sentry
capture happens out of band.

Note on the catch-all `Exception` handler: FastAPI promotes a handler
registered against `Exception` (or status 500) to Starlette's
`ServerErrorMiddleware`, which sits OUTSIDE `RequestIdMiddleware` (which
is a `BaseHTTPMiddleware` and runs the route in a wrapper task). By the
time the 500 handler fires, the request-id `ContextVar` has been reset.
We therefore read `request.state.request_id` (set by the middleware before
the route runs) as the authoritative source.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any, Final

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from vaultchain.shared.delivery.middleware import get_request_id
from vaultchain.shared.domain.errors import DomainError

DOC_URL_PREFIX: Final[str] = "https://docs.vaultchain.example/errors/"
GENERIC_500_MESSAGE: Final[str] = (
    "Something went wrong on our end. Reference {request_id} when contacting " "support."
)

_log = structlog.get_logger(__name__)


class ErrorBody(BaseModel):
    """Inner body of an error response."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(examples=["validation.invalid_input"])
    message: str = Field(examples=["Request input is invalid."])
    details: dict[str, Any] = Field(
        default_factory=dict,
        examples=[{"field": "amount", "minimum_wei": "100000000000000"}],
    )
    request_id: str = Field(examples=["req_01HW..."])
    documentation_url: str = Field(
        examples=[f"{DOC_URL_PREFIX}validation.invalid_input"],
    )


class ErrorEnvelope(BaseModel):
    """Canonical response shape for every 4xx/5xx coming out of the API."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorBody


def _resolve_request_id(request: Request) -> str:
    """Pick request_id from `request.state` first, then ContextVar, then empty."""
    state_id = getattr(request.state, "request_id", None)
    if state_id:
        return str(state_id)
    ctx_id = get_request_id()
    return ctx_id or ""


def _envelope(
    *,
    request: Request,
    code: str,
    message: str,
    details: dict[str, Any] | None,
    status_code: int,
) -> JSONResponse:
    request_id = _resolve_request_id(request)
    body = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            details=details or {},
            request_id=request_id,
            documentation_url=f"{DOC_URL_PREFIX}{code}",
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
    )


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map any `DomainError` subclass to its `status_code` + envelope."""
    assert isinstance(exc, DomainError)
    return _envelope(
        request=request,
        code=exc.code,
        message=exc.message,
        details=exc.details,
        status_code=exc.status_code,
    )


async def request_validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Override FastAPI's default Pydantic-validation envelope.

    Default FastAPI returns `{"detail": [...]}`; we replace it so every error
    from the API has identical shape.
    """
    assert isinstance(exc, RequestValidationError)
    fields = [
        {
            "loc": list(err.get("loc", [])),
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    return _envelope(
        request=request,
        code="validation.request_schema",
        message="Request payload failed schema validation.",
        details={"fields": fields},
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all 500 — never leak internals; log full trace via structlog."""
    request_id = _resolve_request_id(request)
    _log.exception(
        "internal.unexpected",
        request_id=request_id,
        exc_class=type(exc).__qualname__,
    )
    return _envelope(
        request=request,
        code="internal.unexpected",
        message=GENERIC_500_MESSAGE.format(request_id=request_id),
        details=None,
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install the canonical exception handlers on `app`."""
    # Order: most-specific Pydantic schema error first, then DomainError
    # for every domain-modelled failure, then a catch-all for anything else.
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


__all__ = [
    "DOC_URL_PREFIX",
    "ErrorBody",
    "ErrorEnvelope",
    "domain_error_handler",
    "register_error_handlers",
    "request_validation_error_handler",
    "unhandled_exception_handler",
]
