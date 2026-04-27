"""FastAPI app factory — composition root.

Phase 1 briefs (shared-002+) wire concrete routers, middleware, dependency
overrides, and lifespan handlers. For bootstrap this exposes only /healthz
so deploy + CI can validate the app boots.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from vaultchain.config import get_settings


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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
