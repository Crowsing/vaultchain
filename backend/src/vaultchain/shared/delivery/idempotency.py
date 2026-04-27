"""HTTP-layer idempotency middleware (architecture-decisions Section 4).

Pure ASGI implementation — runs outside `BaseHTTPMiddleware` so it can buffer
the request body once and re-stream it cleanly to the route handler. Pairs
with a domain-layer DB UNIQUE constraint on `transactions.idempotency_key`
(arrives in Phase 2) — the cache is the fast path; the constraint is the
final line of defence.

Cache key format: `idempotency:{actor}:{path}:{idempotency_key}` where `actor`
is the user_id (when auth wires up in Phase 2) or the client IP otherwise.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, Final

import structlog
from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from vaultchain.shared.delivery.error_handlers import (
    DOC_URL_PREFIX,
    unhandled_exception_handler,
)
from vaultchain.shared.delivery.middleware import get_request_id
from vaultchain.shared.domain.ports import CachedResponse, IdempotencyStore
from vaultchain.shared.infra.idempotency import StoreUnavailable

DEFAULT_TTL_SECONDS: Final[int] = 86_400  # 24h — generous retry window per ADR
MAX_KEY_LENGTH: Final[int] = 200
NON_IDEMPOTENT_HEADERS: Final[frozenset[str]] = frozenset(
    {
        "set-cookie",
        "www-authenticate",
        "proxy-authenticate",
        "authorization",
    }
)
SAFE_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})

_log = structlog.get_logger(__name__)


def _find_header(scope: Scope, name: bytes) -> str | None:
    target = name.lower()
    for key, value in scope.get("headers", []):
        if key.lower() == target:
            return str(value.decode("latin-1"))
    return None


async def _read_body(receive: Receive) -> tuple[bytes, list[Message]]:
    """Drain the http.request stream; return raw body + the original messages."""
    chunks: list[Message] = []
    body = b""
    while True:
        msg = await receive()
        chunks.append(msg)
        if msg["type"] == "http.disconnect":
            break
        body += msg.get("body", b"")
        if not msg.get("more_body", False):
            break
    return body, chunks


def _replay_receive(buffered: list[Message], real: Receive) -> Receive:
    queue = list(buffered)

    async def _recv() -> Message:
        if queue:
            return queue.pop(0)
        return await real()

    return _recv


class _ResponseCaptor:
    """Stash response.start + response.body messages so we can both forward
    and cache them after the inner app finishes."""

    def __init__(self) -> None:
        self.start: Message | None = None
        self.bodies: list[Message] = []

    async def send(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.start = message
        elif message["type"] == "http.response.body":
            self.bodies.append(message)

    def status_code(self) -> int:
        if self.start is None:
            return 500
        return int(self.start.get("status", 500))

    def headers(self) -> list[tuple[str, str]]:
        if self.start is None:
            return []
        return [
            (k.decode("latin-1"), v.decode("latin-1")) for k, v in self.start.get("headers", [])
        ]

    def body(self) -> bytes:
        return b"".join(m.get("body", b"") for m in self.bodies)

    async def replay_to(self, send: Send) -> None:
        if self.start is not None:
            await send(self.start)
        for chunk in self.bodies:
            await send(chunk)

    def to_cached(self) -> CachedResponse:
        kept_headers = [
            (k, v) for k, v in self.headers() if k.lower() not in NON_IDEMPOTENT_HEADERS
        ]
        return CachedResponse(
            status_code=self.status_code(),
            headers=kept_headers,
            body=self.body(),
        )


def _build_cache_key(scope: Scope, idem_key: str) -> str:
    state = scope.get("state")
    actor: str | None = None
    if state is not None:
        try:
            actor = getattr(state, "user_id", None)
        except AttributeError:
            actor = None
    if not actor:
        client = scope.get("client")
        actor = client[0] if client and client[0] else "anonymous"
    path = scope.get("path", "/")
    return f"idempotency:{actor}:{path}:{idem_key}"


def _request_id_for(scope: Scope) -> str:
    state = scope.get("state")
    if state is not None:
        rid = getattr(state, "request_id", None)
        if rid:
            return str(rid)
    return get_request_id() or ""


def _envelope_bytes(*, code: str, message: str, details: dict[str, Any], request_id: str) -> bytes:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
            "documentation_url": f"{DOC_URL_PREFIX}{code}",
        }
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


async def _send_envelope(
    send: Send,
    *,
    status: int,
    code: str,
    message: str,
    details: dict[str, Any],
    request_id: str,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = _envelope_bytes(code=code, message=message, details=details, request_id=request_id)
    headers: list[tuple[bytes, bytes]] = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if extra_headers:
        headers.extend(extra_headers)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _send_cached(send: Send, cached: CachedResponse) -> None:
    headers = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in cached.headers]
    await send({"type": "http.response.start", "status": cached.status_code, "headers": headers})
    await send({"type": "http.response.body", "body": cached.body, "more_body": False})


class IdempotencyMiddleware:
    """ASGI middleware enforcing Stripe-style HTTP-layer idempotency."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: IdempotencyStore,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.app = app
        self.store = store
        self.ttl_seconds = ttl_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Pass-through: anything that isn't an HTTP call with a key on a mutating verb.
        if (
            scope["type"] != "http"
            or scope.get("method", "") in SAFE_METHODS
            or (idem_key := _find_header(scope, b"idempotency-key")) is None
        ):
            await self.app(scope, receive, send)
            return
        if len(idem_key) > MAX_KEY_LENGTH:
            await _send_envelope(
                send,
                status=422,
                code="validation.idempotency_key_too_long",
                message=f"Idempotency-Key exceeds {MAX_KEY_LENGTH} characters.",
                details={"max_length": MAX_KEY_LENGTH, "actual_length": len(idem_key)},
                request_id=_request_id_for(scope),
            )
            return

        body, body_messages = await _read_body(receive)
        body_hash = hashlib.sha256(body).hexdigest()
        cache_key = _build_cache_key(scope, idem_key)

        try:
            claimed = await self.store.claim(cache_key, body_hash, self.ttl_seconds)
        except StoreUnavailable as exc:
            return await self._fail_open(scope, body_messages, receive, send, exc, idem_key)

        if not claimed:
            return await self._handle_existing(
                scope, send, cache_key, body_hash, body_messages, receive, idem_key
            )

        # We own the key — run the inner app and capture the response.
        captor = _ResponseCaptor()
        replay = _replay_receive(body_messages, receive)
        try:
            await self.app(scope, replay, captor.send)
        except Exception as exc:  # pragma: no cover — exercised via tests
            request = Request(scope)
            response = await unhandled_exception_handler(request, exc)
            cached = CachedResponse(
                status_code=response.status_code,
                headers=[
                    (k.decode("latin-1"), v.decode("latin-1"))
                    for k, v in response.raw_headers
                    if k.decode("latin-1").lower() not in NON_IDEMPOTENT_HEADERS
                ],
                body=bytes(response.body),
            )
            try:
                await self.store.complete(cache_key, body_hash, cached, self.ttl_seconds)
            except StoreUnavailable:
                _log.warning("idempotency.complete_failed", path=scope.get("path"))
            await _send_cached(send, cached)
            return

        cached = captor.to_cached()
        try:
            await self.store.complete(cache_key, body_hash, cached, self.ttl_seconds)
        except StoreUnavailable:
            _log.warning("idempotency.complete_failed", path=scope.get("path"))
        await captor.replay_to(send)

    async def _handle_existing(
        self,
        scope: Scope,
        send: Send,
        cache_key: str,
        body_hash: str,
        body_messages: list[Message],
        receive: Receive,
        idem_key: str,
    ) -> None:
        try:
            entry = await self.store.get(cache_key)
        except StoreUnavailable as exc:
            await self._fail_open(scope, body_messages, receive, send, exc, idem_key)
            return
        if entry is None:
            # Lost-the-race-then-TTL-expired edge: degrade gracefully.
            await self._fail_open(
                scope, body_messages, receive, send, RuntimeError("entry vanished"), idem_key
            )
            return
        if entry.state == "in_flight":
            await _send_envelope(
                send,
                status=409,
                code="idempotency.in_flight",
                message=(
                    "A request with this Idempotency-Key is already in flight; retry shortly."
                ),
                details={},
                request_id=_request_id_for(scope),
            )
            return
        if entry.body_hash != body_hash:
            await _send_envelope(
                send,
                status=422,
                code="idempotency.conflict_body_mismatch",
                message="Idempotency-Key was reused with a different request body.",
                details={
                    "original_body_hash": entry.body_hash,
                    "actual_body_hash": body_hash,
                },
                request_id=_request_id_for(scope),
            )
            return
        if entry.response is None:
            # Should be unreachable in well-formed entries; degrade safely.
            await self._fail_open(
                scope,
                body_messages,
                receive,
                send,
                RuntimeError("done entry without response"),
                idem_key,
            )
            return
        await _send_cached(send, entry.response)

    async def _fail_open(
        self,
        scope: Scope,
        body_messages: list[Message],
        receive: Receive,
        send: Send,
        exc: BaseException,
        idem_key: str,
    ) -> None:
        _log.warning(
            "idempotency.store_unavailable",
            path=scope.get("path"),
            idempotency_key=idem_key,
            error=str(exc),
        )
        replay = _replay_receive(body_messages, receive)

        async def _send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                new_headers = list(message.get("headers", []))
                new_headers.append((b"x-idempotency-disabled", b"1"))
                message = {**message, "headers": new_headers}
            await send(message)

        await self.app(scope, replay, _send_with_header)


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "IdempotencyMiddleware",
    "MAX_KEY_LENGTH",
    "NON_IDEMPOTENT_HEADERS",
]

# Keep imports tidy for static analysis.
_: Callable[..., Awaitable[None]] = _send_envelope
