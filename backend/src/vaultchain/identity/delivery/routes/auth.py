"""Magic-link + session lifecycle routes — AC-phase1-identity-005-01..03,07.

This module owns:

- ``POST /auth/request``     magic-link issuance (idempotency-key tolerant)
- ``POST /auth/verify``      magic-link consume + pre-TOTP token mint
- ``POST /auth/refresh``     session refresh (rotates cookies)
- ``POST /auth/logout``      session revocation (clears cookies)

Cookie composition lives in the route handler, not the use case —
the use case returns raw tokens; the route calls
``set_session_cookies`` / ``clear_session_cookies`` from
``identity/infra/tokens/cookies.py`` (delivered by phase1-identity-004).
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from vaultchain.identity.application.consume_magic_link import ConsumeMagicLink
from vaultchain.identity.application.create_session import CreateSession
from vaultchain.identity.application.refresh_session import RefreshSession
from vaultchain.identity.application.request_magic_link import RequestMagicLink
from vaultchain.identity.application.revoke_session import RevokeSession
from vaultchain.identity.delivery.composition import (
    get_consume_magic_link,
    get_csrf_guard,
    get_current_user,
    get_pre_totp_cache,
    get_refresh_session,
    get_request_magic_link,
    get_revoke_session,
)
from vaultchain.identity.delivery.dependencies.csrf import CsrfGuard
from vaultchain.identity.delivery.dependencies.current_user import (
    GetCurrentUser,
    UserContext,
)
from vaultchain.identity.delivery.schemas import (
    AuthRequestBody,
    AuthRequestResponse,
    AuthVerifyBody,
    AuthVerifyResponse,
)
from vaultchain.identity.domain.aggregates import MagicLinkMode
from vaultchain.identity.domain.errors import RefreshTokenInvalid
from vaultchain.identity.domain.ports import (
    PreTotpIntent,
    PreTotpPayload,
    PreTotpTokenCache,
)
from vaultchain.identity.infra.tokens.cookies import (
    REFRESH_COOKIE_NAME,
    clear_session_cookies,
    set_session_cookies,
)
from vaultchain.identity.infra.tokens.hashing import sha256_hex

router = APIRouter(prefix="/auth", tags=["auth"])

#: Bytes of randomness for the pre-TOTP bearer; same envelope as access token.
_PRE_TOTP_BYTES = 32


@router.post(
    "/request",
    response_model=AuthRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Issue a magic link",
)
async def auth_request(
    body: AuthRequestBody,
    use_case: Annotated[RequestMagicLink, Depends(get_request_magic_link)],
) -> AuthRequestResponse:
    """Request a magic link for the supplied email / mode.

    Idempotent on email — calling twice creates two distinct magic
    links; both stay valid until consumed/expired. The HTTP idempotency
    middleware (``Idempotency-Key`` header) collapses verbatim retries
    into a single response.
    """
    await use_case.execute(email=body.email, mode=body.mode)
    return AuthRequestResponse(message_sent=True)


@router.post(
    "/verify",
    response_model=AuthVerifyResponse,
    summary="Consume a magic link and mint a pre-TOTP token",
)
async def auth_verify(
    body: AuthVerifyBody,
    use_case: Annotated[ConsumeMagicLink, Depends(get_consume_magic_link)],
    pre_totp_cache: Annotated[PreTotpTokenCache, Depends(get_pre_totp_cache)],
) -> AuthVerifyResponse:
    """Consume the raw magic-link token; on success mint a 5-min Redis-cached
    pre-TOTP bearer token that gates the TOTP routes.
    """
    result = await use_case.execute(raw_token=body.token)

    pre_totp_token = secrets.token_urlsafe(_PRE_TOTP_BYTES)
    intent = PreTotpIntent.ENROLL if result.is_first_time else PreTotpIntent.CHALLENGE
    await pre_totp_cache.set(
        sha256_hex(pre_totp_token),
        PreTotpPayload(user_id=result.user_id, intent=intent),
    )

    # Look up the email for the response. The use case doesn't return it
    # to keep the result narrow; the user repo gives us a single fetch.
    # We avoid loading via UoW here — the use case already committed.
    # The /me-style read will run on its own; for the verify response
    # we return the email the client typed (which `body` carries
    # implicitly only for `request`, not `verify`). To stay correct,
    # query through the cache's user_id once via the get_current_user
    # path — but that requires a session token. So we do a one-off
    # read using the same composition.
    email = await _fetch_email(result.user_id, use_case)

    return AuthVerifyResponse(
        user_id=result.user_id,
        email=email,
        is_first_time=result.is_first_time,
        requires_totp_enrollment=result.is_first_time,
        requires_totp_challenge=not result.is_first_time,
        pre_totp_token=pre_totp_token,
    )


async def _fetch_email(user_id, use_case: ConsumeMagicLink) -> str:  # type: ignore[no-untyped-def]
    """Pull the email through the same UoW factory the use case uses.

    Accessing the user repo via a fresh UoW. Email is a small, stable
    string, so a single SELECT is acceptable.
    """
    async with use_case._uow_factory() as uow:
        user = await use_case._users(uow.session).get_by_id(user_id)
    if user is None:
        # Defensive — magic link existed for this user_id moments ago.
        return ""
    return user.email


@router.post(
    "/refresh",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Rotate session cookies",
)
async def auth_refresh(
    response: Response,
    use_case: Annotated[RefreshSession, Depends(get_refresh_session)],
    refresh_cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
) -> None:
    """Rotate the refresh-token + access-token + CSRF cookies."""
    if not refresh_cookie:
        raise RefreshTokenInvalid(details={"reason": "missing_refresh_cookie"})

    result = await use_case.execute(refresh_token_raw=refresh_cookie)
    set_session_cookies(
        response,
        access_token=result.access_token_raw,
        refresh_token=result.refresh_token_raw,
        csrf_token=result.csrf_token_raw,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke the current session",
    dependencies=[Depends(get_csrf_guard)],
)
async def auth_logout(
    request: Request,
    response: Response,
    user_ctx: Annotated[UserContext, Depends(get_current_user)],
    use_case: Annotated[RevokeSession, Depends(get_revoke_session)],
) -> None:
    """Revoke the current session and clear cookies."""
    await use_case.execute(session_id=user_ctx.session_id)
    clear_session_cookies(response)


# Touch unused-import-friendly modules for IDE imports stability.
_ = (CsrfGuard, GetCurrentUser, MagicLinkMode, CreateSession)


__all__ = ["router"]
