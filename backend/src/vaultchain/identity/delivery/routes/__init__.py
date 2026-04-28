"""Identity routers — assemble all auth + me endpoints into one APIRouter."""

from __future__ import annotations

from fastapi import APIRouter

from vaultchain.identity.delivery.routes.auth import router as auth_router
from vaultchain.identity.delivery.routes.me import router as me_router
from vaultchain.identity.delivery.routes.totp import router as totp_router


def build_identity_router() -> APIRouter:
    """One ``/api/v1`` router that mounts the three sub-routers."""
    api = APIRouter(prefix="/api/v1")
    api.include_router(auth_router)
    api.include_router(totp_router)
    api.include_router(me_router)
    return api


__all__ = ["build_identity_router"]
