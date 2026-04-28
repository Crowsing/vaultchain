"""FastAPI app factory — composition root.

Phase 1 briefs (shared-002+) wire concrete routers, middleware, dependency
overrides, and lifespan handlers. For bootstrap this exposes only /healthz
so deploy + CI can validate the app boots.

`phase1-shared-005` adds the canonical error envelope: a request-id
middleware that stamps every request, plus exception handlers that translate
`DomainError` subclasses, FastAPI's `RequestValidationError`, and any
unhandled `Exception` into the `{error: {...}}` shape.

`phase1-shared-006` adds Stripe-style HTTP idempotency on top: every mutating
request that carries an `Idempotency-Key` header is deduplicated against a
Redis-backed store. The cache is the fast path; a DB UNIQUE constraint on
`transactions.idempotency_key` (Phase 2) is the durable safety net.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from vaultchain.config import get_settings
from vaultchain.identity.delivery.composition import (
    install_identity_dependencies,
    shutdown_identity_dependencies,
)
from vaultchain.identity.delivery.routes import build_admin_router, build_identity_router
from vaultchain.shared.delivery import RequestIdMiddleware, register_error_handlers
from vaultchain.shared.delivery.idempotency import IdempotencyMiddleware
from vaultchain.shared.infra.idempotency import RedisIdempotencyStore


def _install_idempotency_openapi(app: FastAPI) -> None:
    """Declare a reusable `IdempotencyKey` header parameter component.

    Route-level `$ref` wiring lands in subsequent briefs (shared-006 only ships
    the reusable component definition).
    """

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description or None,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        parameters = components.setdefault("parameters", {})
        parameters["IdempotencyKey"] = {
            "name": "Idempotency-Key",
            "in": "header",
            "required": False,
            "schema": {"type": "string", "maxLength": 200},
            "description": (
                "Opaque client-generated key (≤200 chars). Replays return the cached "
                "response; mismatched bodies on the same key return 422."
            ),
        }
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def create_app() -> FastAPI:
    settings = get_settings()
    idempotency_store = RedisIdempotencyStore.from_url(settings.redis_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await idempotency_store.aclose()
            await shutdown_identity_dependencies(app)

    app = FastAPI(
        title="VaultChain API",
        version="0.1.0",
        lifespan=lifespan,
        debug=(settings.environment == "dev"),
    )
    # Stack (outermost first): CORS → Idempotency → RequestId → Exception.
    # Idempotency must outer-wrap RequestId so the cached response carries the
    # request-id of the *original* request, not the replay.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(IdempotencyMiddleware, store=idempotency_store)
    app.add_middleware(RequestIdMiddleware)

    register_error_handlers(app)
    _install_idempotency_openapi(app)
    install_identity_dependencies(app, settings)
    app.include_router(build_identity_router())
    app.include_router(build_admin_router())

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
