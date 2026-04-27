"""Request-ID middleware.

Reads `X-Request-ID` from the incoming request when present, generates a
fresh `req_<32 hex chars>` token otherwise, and exposes the value to the
rest of the stack via:

  * a `contextvars.ContextVar` (so error handlers and use cases can read it
    without threading it through every call),
  * `structlog.contextvars` (so every log line emitted while the request is
    in flight carries the same `request_id`),
  * the `X-Request-ID` response header (so clients can echo it back to
    support and operators can correlate browser → server logs).
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Final

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER: Final[str] = "X-Request-ID"

_request_id_ctx: ContextVar[str | None] = ContextVar("vaultchain_request_id", default=None)


def get_request_id() -> str | None:
    """Return the request-id bound to the current async task, or None."""
    return _request_id_ctx.get()


def _generate_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Stamp every request with a stable correlation id."""

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming if incoming else _generate_request_id()

        ctx_token = _request_id_ctx.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
            _request_id_ctx.reset(ctx_token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
