"""Identity routers — assemble all auth + me endpoints into one APIRouter."""

from __future__ import annotations

from fastapi import APIRouter

from vaultchain.identity.delivery.routes.admin_auth import router as admin_auth_router
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


def build_admin_router() -> APIRouter:
    """Admin auth tree mounted at ``/admin/api/v1/auth``; the inner
    router carries ``include_in_schema=False`` so the public OpenAPI
    surface stays clean per architecture-decisions Section 4.
    """
    return admin_auth_router


__all__ = ["build_admin_router", "build_identity_router"]
