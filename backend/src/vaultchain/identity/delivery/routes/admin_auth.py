"""Admin auth router — phase1-admin-002a AC-01..05.

Endpoints under ``/admin/api/v1/auth``:

- ``POST /login``         email + password → pre-TOTP token (cookie + body flag)
- ``POST /totp/verify``   pre-TOTP cookie + 6-digit code → admin session cookies
- ``POST /logout``        revoke admin session
- ``GET  /me``            admin profile

Whole tree is filtered out of the public OpenAPI surface
(``include_in_schema=False``) per architecture-decisions Section 4.
The matching admin-side OpenAPI doc is exposed at ``/admin/openapi.json``
behind the admin session check.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from vaultchain.identity.application.admin_login import AdminLogin
from vaultchain.identity.application.admin_totp_verify import AdminTotpVerify
from vaultchain.identity.application.revoke_session import RevokeSession
from vaultchain.identity.delivery.composition import (
    get_admin_login,
    get_admin_totp_verify,
    get_csrf_guard,
    get_current_admin,
    get_pre_totp_cache,
    get_revoke_session,
)
from vaultchain.identity.delivery.dependencies.admin_user import AdminContext
from vaultchain.identity.delivery.dependencies.csrf import CsrfGuard
from vaultchain.identity.delivery.schemas import (
    AdminLoginBody,
    AdminLoginResponse,
    AdminMeResponse,
    AdminTotpVerifyBody,
    AdminTotpVerifyResponse,
    AdminUserSummary,
)
from vaultchain.identity.domain.errors import PreTotpTokenInvalid
from vaultchain.identity.domain.ports import (
    PreTotpIntent,
    PreTotpPayload,
    PreTotpTokenCache,
)
from vaultchain.identity.infra.tokens.cookies import (
    ADMIN_COOKIE_CONFIG,
    ADMIN_PRE_TOTP_COOKIE_NAME,
    clear_admin_pre_totp_cookie,
    clear_session_cookies,
    set_admin_pre_totp_cookie,
    set_session_cookies,
)
from vaultchain.identity.infra.tokens.hashing import sha256_hex

router = APIRouter(
    prefix="/admin/api/v1/auth",
    tags=["admin-auth"],
    include_in_schema=False,
)

#: Match user-side pre-TOTP token entropy for protocol uniformity.
_PRE_TOTP_BYTES = 32


@router.post(
    "/login",
    response_model=AdminLoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify admin password and mint a pre-TOTP cookie",
)
async def admin_login(
    body: AdminLoginBody,
    response: Response,
    use_case: Annotated[AdminLogin, Depends(get_admin_login)],
    pre_totp_cache: Annotated[PreTotpTokenCache, Depends(get_pre_totp_cache)],
) -> AdminLoginResponse:
    result = await use_case.execute(email=body.email, password=body.password)

    pre_totp_token = secrets.token_urlsafe(_PRE_TOTP_BYTES)
    await pre_totp_cache.set(
        sha256_hex(pre_totp_token),
        PreTotpPayload(user_id=result.user_id, intent=PreTotpIntent.CHALLENGE),
    )
    set_admin_pre_totp_cookie(response, token=pre_totp_token)
    return AdminLoginResponse(pre_totp_required=True)


@router.post(
    "/totp/verify",
    response_model=AdminTotpVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify admin TOTP and mint session cookies",
)
async def admin_totp_verify(
    body: AdminTotpVerifyBody,
    request: Request,
    response: Response,
    use_case: Annotated[AdminTotpVerify, Depends(get_admin_totp_verify)],
    pre_totp_cache: Annotated[PreTotpTokenCache, Depends(get_pre_totp_cache)],
    pre_totp_cookie: Annotated[str | None, Cookie(alias=ADMIN_PRE_TOTP_COOKIE_NAME)] = None,
) -> AdminTotpVerifyResponse:
    if not pre_totp_cookie:
        raise PreTotpTokenInvalid(details={"reason": "missing_admin_pre_totp_cookie"})

    token_hash = sha256_hex(pre_totp_cookie)
    payload = await pre_totp_cache.get(token_hash)
    if payload is None:
        raise PreTotpTokenInvalid(details={"reason": "unknown_or_expired"})
    if payload.intent is not PreTotpIntent.CHALLENGE:
        raise PreTotpTokenInvalid(
            details={"reason": "intent_mismatch", "expected": PreTotpIntent.CHALLENGE.value}
        )

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "")

    result = await use_case.execute(
        user_id=payload.user_id,
        code=body.code,
        ip=ip,
        user_agent=user_agent,
    )

    # Single-use consumption.
    await pre_totp_cache.evict(token_hash)
    clear_admin_pre_totp_cookie(response)

    set_session_cookies(
        response,
        access_token=result.session.access_token_raw,
        refresh_token=result.session.refresh_token_raw,
        csrf_token=result.session.csrf_token_raw,
        config=ADMIN_COOKIE_CONFIG,
    )

    return AdminTotpVerifyResponse(
        user=AdminUserSummary(
            id=result.user_id,
            email=result.email,
            actor_type="admin",
        )
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke the current admin session",
    dependencies=[Depends(get_csrf_guard)],
)
async def admin_logout(
    response: Response,
    admin_ctx: Annotated[AdminContext, Depends(get_current_admin)],
    use_case: Annotated[RevokeSession, Depends(get_revoke_session)],
) -> None:
    await use_case.execute(session_id=admin_ctx.session_id)
    clear_session_cookies(response, config=ADMIN_COOKIE_CONFIG)


@router.get(
    "/me",
    response_model=AdminMeResponse,
    summary="Return the authenticated admin's profile",
)
async def admin_me(
    admin_ctx: Annotated[AdminContext, Depends(get_current_admin)],
) -> AdminMeResponse:
    user = admin_ctx.user
    return AdminMeResponse(
        id=user.id,
        email=user.email,
        full_name=str(user.metadata.get("full_name", "")),
        role=str(user.metadata.get("admin_role", "admin")),
        last_login_at=user.updated_at,
    )


# Touch unused imports defensively.
_ = (CsrfGuard, datetime, UTC)


__all__ = ["router"]
