"""`get_current_user` FastAPI dependency — AC-phase1-identity-004-03.

Resolves the current request's User by:
  1. Reading the ``vc_at`` cookie.
  2. Hashing it (sha256) and looking up the cached payload.
  3. Loading the User from the repository to honour current ``status``.

The dependency raises ``Unauthenticated`` when no/expired token, and
``UserLocked`` when the user's ``status == LOCKED``. Subsequent log
records in the request carry ``user_id`` via structlog contextvars.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import structlog

from vaultchain.identity.domain.aggregates import User, UserStatus
from vaultchain.identity.domain.errors import Unauthenticated, UserLocked
from vaultchain.identity.domain.ports import AccessTokenCache, UserRepository
from vaultchain.identity.infra.tokens.cookies import ACCESS_COOKIE_NAME
from vaultchain.identity.infra.tokens.hashing import sha256_hex
from vaultchain.shared.unit_of_work import AbstractUnitOfWork


class _RequestLike(Protocol):
    """Subset of ``starlette.requests.Request`` we depend on."""

    @property
    def cookies(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class UserContext:
    """What the dependency hands to the route handler."""

    user: User
    session_id: UUID
    scopes: tuple[str, ...]


class GetCurrentUser:
    """Callable dependency — instantiate at app startup, attach via FastAPI's
    ``Depends(GetCurrentUser(...))`` shape so testing remains a constructor
    call away from any session adapter.
    """

    def __init__(
        self,
        *,
        cache: AccessTokenCache,
        uow_factory: Callable[[], AbstractUnitOfWork],
        users: Callable[[Any], UserRepository],
    ) -> None:
        self._cache = cache
        self._uow_factory = uow_factory
        self._users = users

    async def __call__(self, request: _RequestLike) -> UserContext:
        token_raw = request.cookies.get(ACCESS_COOKIE_NAME)
        if not token_raw:
            raise Unauthenticated(details={"reason": "missing_token_cookie"})

        cached = await self._cache.get(sha256_hex(token_raw))
        if cached is None:
            raise Unauthenticated(details={"reason": "token_expired_or_unknown"})

        async with self._uow_factory() as uow:
            user = await self._users(uow.session).get_by_id(cached.user_id)
        if user is None:
            raise Unauthenticated(details={"reason": "user_missing"})
        if user.status is UserStatus.LOCKED:
            raise UserLocked(
                details={
                    "user_id": str(user.id),
                    "locked_until": user.locked_until.isoformat() if user.locked_until else None,
                }
            )

        # Bind for downstream structlog records (per brief Implementation Notes).
        structlog.contextvars.bind_contextvars(
            user_id=str(user.id), session_id=str(cached.session_id)
        )
        return UserContext(user=user, session_id=cached.session_id, scopes=cached.scopes)


__all__ = ["GetCurrentUser", "UserContext"]
