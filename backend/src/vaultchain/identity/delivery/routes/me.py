"""Profile route — AC-phase1-identity-005-01."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from vaultchain.identity.delivery.composition import (
    get_current_user,
    get_totp_repo_factory,
    get_uow_factory,
)
from vaultchain.identity.delivery.dependencies.current_user import UserContext
from vaultchain.identity.delivery.schemas import MeResponse
from vaultchain.identity.domain.errors import TotpRequired
from vaultchain.shared.unit_of_work import AbstractUnitOfWork

router = APIRouter(tags=["me"])


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return the authenticated user's profile",
)
async def me(
    user_ctx: Annotated[UserContext, Depends(get_current_user)],
    uow_factory: Annotated[Callable[[], AbstractUnitOfWork], Depends(get_uow_factory)],
    totps_factory: Annotated[Callable[[Any], Any], Depends(get_totp_repo_factory)],
) -> MeResponse:
    """The simplest authenticated route — proves the cookie + cache
    pipeline works end-to-end.
    """
    user = user_ctx.user
    # Probe TOTP enrollment so the response can flag clients that
    # somehow reached this route without enrolling. Per AC-04 we also
    # raise on access — but only if the user has the verified status
    # AND no TOTP secret. For now we surface the status as-is and let
    # the frontend act on `totp_enrolled`.
    async with uow_factory() as uow:
        secret = await totps_factory(uow.session).get_by_user_id(user.id)
    totp_enrolled = secret is not None

    if not totp_enrolled and user.status.value == "verified":
        # Defensive last-line per AC-04. Frontend should never trigger
        # this in practice — `is_first_time` from `/auth/verify` tells
        # it to enroll first.
        raise TotpRequired(details={"user_id": str(user.id)})

    return MeResponse(
        id=user.id,
        email=user.email,
        status=user.status.value,
        kyc_tier=user.kyc_tier,
        totp_enrolled=totp_enrolled,
        created_at=user.created_at,
    )


__all__ = ["router"]
