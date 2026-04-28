"""TOTP enrollment + verification routes — AC-phase1-identity-005-01,03,05.

Pre-TOTP-token gated:

- ``POST /auth/totp/enroll``                 intent=enroll
- ``POST /auth/totp/enroll/confirm``         intent=enroll, mints session
- ``POST /auth/totp/verify``                 intent=challenge, mints session
- ``POST /auth/totp/backup-codes/regenerate``session-protected (full auth)
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from vaultchain.identity.application.create_session import CreateSession
from vaultchain.identity.application.enroll_totp import EnrollTotp
from vaultchain.identity.application.regenerate_backup_codes import RegenerateBackupCodes
from vaultchain.identity.application.verify_totp import VerifyTotp
from vaultchain.identity.delivery.composition import (
    get_create_session,
    get_csrf_guard,
    get_current_user,
    get_enroll_totp,
    get_pre_totp_cache,
    get_regenerate_backup_codes,
    get_verify_totp,
)
from vaultchain.identity.delivery.dependencies.csrf import CsrfGuard
from vaultchain.identity.delivery.dependencies.current_user import (
    GetCurrentUser,
    UserContext,
)
from vaultchain.identity.delivery.dependencies.pre_totp import make_get_pre_totp_user
from vaultchain.identity.delivery.schemas import (
    BackupCodesRegenerateResponse,
    TotpEnrollConfirmBody,
    TotpEnrollResponse,
    TotpVerifyBody,
    TotpVerifyResponse,
)
from vaultchain.identity.domain.errors import PreTotpTokenInvalid
from vaultchain.identity.domain.ports import PreTotpIntent, PreTotpTokenCache
from vaultchain.identity.infra.tokens.cookies import set_session_cookies
from vaultchain.identity.infra.tokens.hashing import sha256_hex

router = APIRouter(prefix="/auth/totp", tags=["auth-totp"])


def _resolve_pre_totp_user(intent: PreTotpIntent):  # type: ignore[no-untyped-def]
    """Wrap `make_get_pre_totp_user` so FastAPI can call it with Depends."""

    async def dependency(
        request: Request,
        cache: Annotated[PreTotpTokenCache, Depends(get_pre_totp_cache)],
    ) -> UUID:
        bound = make_get_pre_totp_user(cache=cache, intent=intent)
        return await bound(request)

    return dependency


_resolve_enroll_user = _resolve_pre_totp_user(PreTotpIntent.ENROLL)
_resolve_challenge_user = _resolve_pre_totp_user(PreTotpIntent.CHALLENGE)


@router.post(
    "/enroll",
    response_model=TotpEnrollResponse,
    summary="Generate a fresh TOTP secret + 10 backup codes (one-shot)",
)
async def totp_enroll(
    user_id: Annotated[UUID, Depends(_resolve_enroll_user)],
    use_case: Annotated[EnrollTotp, Depends(get_enroll_totp)],
) -> TotpEnrollResponse:
    """Returns the secret/QR/backup codes exactly once. Bearer token is
    NOT consumed yet — the client also calls ``/enroll/confirm`` with
    the same token to actually mint the session.
    """
    result = await use_case.execute(user_id=user_id)
    return TotpEnrollResponse(
        secret_for_qr=result.secret_for_qr,
        qr_payload_uri=result.qr_payload_uri,
        backup_codes=result.backup_codes_plaintext,
    )


@router.post(
    "/enroll/confirm",
    response_model=TotpVerifyResponse,
    summary="Confirm enrollment with a code and mint a session",
)
async def totp_enroll_confirm(
    body: TotpEnrollConfirmBody,
    response: Response,
    user_id: Annotated[UUID, Depends(_resolve_enroll_user)],
    verify_uc: Annotated[VerifyTotp, Depends(get_verify_totp)],
    create_uc: Annotated[CreateSession, Depends(get_create_session)],
    pre_totp_cache: Annotated[PreTotpTokenCache, Depends(get_pre_totp_cache)],
    authorization: Annotated[str | None, Header()] = None,
) -> TotpVerifyResponse:
    """Verify the freshly-typed code; on success mint a session and set
    cookies. The pre-TOTP token is evicted so a replay can't mint a
    second session.
    """
    verify_result = await verify_uc.execute(user_id=user_id, code=body.code)
    if not verify_result.success:
        return TotpVerifyResponse(
            success=False, attempts_remaining=verify_result.attempts_remaining
        )
    session = await create_uc.execute(user_id=user_id)
    set_session_cookies(
        response,
        access_token=session.access_token_raw,
        refresh_token=session.refresh_token_raw,
        csrf_token=session.csrf_token_raw,
    )
    if authorization:
        bearer = authorization.partition(" ")[2]
        if bearer:
            await pre_totp_cache.evict(sha256_hex(bearer))
    return TotpVerifyResponse(success=True, attempts_remaining=None)


@router.post(
    "/verify",
    response_model=TotpVerifyResponse,
    summary="Verify a TOTP / backup code on the login flow",
)
async def totp_verify(
    body: TotpVerifyBody,
    response: Response,
    user_id: Annotated[UUID, Depends(_resolve_challenge_user)],
    verify_uc: Annotated[VerifyTotp, Depends(get_verify_totp)],
    create_uc: Annotated[CreateSession, Depends(get_create_session)],
    pre_totp_cache: Annotated[PreTotpTokenCache, Depends(get_pre_totp_cache)],
    authorization: Annotated[str | None, Header()] = None,
) -> TotpVerifyResponse:
    """On success mint a session + cookies; on miss return ``success=false``
    with ``attempts_remaining``; on lockout the use case raises
    ``UserLocked`` which the error envelope renders 403.
    """
    result = await verify_uc.execute(
        user_id=user_id, code=body.code, use_backup_code=body.use_backup_code
    )
    if not result.success:
        return TotpVerifyResponse(success=False, attempts_remaining=result.attempts_remaining)
    session = await create_uc.execute(user_id=user_id)
    set_session_cookies(
        response,
        access_token=session.access_token_raw,
        refresh_token=session.refresh_token_raw,
        csrf_token=session.csrf_token_raw,
    )
    if authorization:
        bearer = authorization.partition(" ")[2]
        if bearer:
            await pre_totp_cache.evict(sha256_hex(bearer))
    return TotpVerifyResponse(success=True, attempts_remaining=None)


@router.post(
    "/backup-codes/regenerate",
    response_model=BackupCodesRegenerateResponse,
    summary="Regenerate the user's backup codes (replaces all 10)",
    dependencies=[Depends(get_csrf_guard)],
)
async def regenerate_backup_codes(
    user_ctx: Annotated[UserContext, Depends(get_current_user)],
    use_case: Annotated[RegenerateBackupCodes, Depends(get_regenerate_backup_codes)],
) -> BackupCodesRegenerateResponse:
    """Recent-TOTP gating — V1 simply requires the session cookie; the
    'recent TOTP' nuance is a Phase 4 polish item per Risk/Friction in
    the brief. Phase 3 may layer in a step-up.
    """
    result = await use_case.execute(user_id=user_ctx.user.id)
    return BackupCodesRegenerateResponse(backup_codes=result.backup_codes_plaintext)


_ = (CsrfGuard, GetCurrentUser, PreTotpTokenInvalid)


__all__ = ["router"]
