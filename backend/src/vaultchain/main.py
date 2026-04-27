"""FastAPI app factory — composition root.

Phase 1 briefs (shared-002+) wire concrete routers, middleware, dependency
overrides, and lifespan handlers. For bootstrap this exposes only /healthz
so deploy + CI can validate the app boots.

`phase1-shared-005` adds the canonical error envelope: a request-id
middleware that stamps every request, plus exception handlers that translate
`DomainError` subclasses, FastAPI's `RequestValidationError`, and any
unhandled `Exception` into the `{error: {...}}` shape.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vaultchain.config import get_settings
from vaultchain.shared.delivery import RequestIdMiddleware, register_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup + shutdown hooks. Phase 1 briefs attach DB engine, Redis pool, etc."""
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="VaultChain API",
        version="0.1.0",
        lifespan=lifespan,
        debug=(settings.environment == "dev"),
    )
    # Register middlewares from outermost to innermost. CORS is outermost so
    # it can decorate every response (including errors). RequestIdMiddleware
    # sits inside CORS so the id is bound for the duration of the actual
    # handler execution and any handler-emitted errors.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIdMiddleware)

    register_error_handlers(app)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
