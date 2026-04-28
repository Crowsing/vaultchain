"""``get_current_admin`` FastAPI dependency — phase1-admin-002a AC-04, AC-05.

Reads the ``admin_at`` cookie, hashes it (sha256), looks up the cached
payload, asserts the cached scope tuple contains ``"admin"``, and
loads the admin User from the repository to honour the current
``status``. Distinct error codes per the brief:

- missing / expired ``admin_at`` cookie -> ``identity.session_required``
- valid token but session is user-actor   -> ``identity.admin_required``
- locked admin                             -> ``identity.user_locked``
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import structlog

from vaultchain.identity.domain.aggregates import User, UserStatus
from vaultchain.identity.domain.errors import AdminRequired, SessionRequired, UserLocked
from vaultchain.identity.domain.ports import AccessTokenCache, UserRepository
from vaultchain.identity.infra.tokens.cookies import ADMIN_ACCESS_COOKIE_NAME
from vaultchain.identity.infra.tokens.hashing import sha256_hex
from vaultchain.shared.unit_of_work import AbstractUnitOfWork


class _RequestLike(Protocol):
    @property
    def cookies(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class AdminContext:
    """Resolved per-request admin handle for route handlers."""

    user: User
    session_id: UUID
    scopes: tuple[str, ...]


class GetCurrentAdmin:
    """Callable dependency mirroring ``GetCurrentUser`` but enforcing
    the admin scope. Built once per app, attached via ``Depends``.
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

    async def __call__(self, request: _RequestLike) -> AdminContext:
        token_raw = request.cookies.get(ADMIN_ACCESS_COOKIE_NAME)
        if not token_raw:
            raise SessionRequired(details={"reason": "missing_admin_at_cookie"})

        cached = await self._cache.get(sha256_hex(token_raw))
        if cached is None:
            raise SessionRequired(details={"reason": "token_expired_or_unknown"})

        if "admin" not in cached.scopes:
            raise AdminRequired(details={"reason": "non_admin_scope"})

        async with self._uow_factory() as uow:
            user = await self._users(uow.session).get_by_id(cached.user_id)
        if user is None:
            raise SessionRequired(details={"reason": "user_missing"})
        if not user.is_admin():
            raise AdminRequired(details={"user_id": str(user.id)})
        if user.status is UserStatus.LOCKED:
            raise UserLocked(
                details={
                    "user_id": str(user.id),
                    "locked_until": user.locked_until.isoformat() if user.locked_until else None,
                }
            )

        structlog.contextvars.bind_contextvars(
            admin_id=str(user.id), session_id=str(cached.session_id)
        )
        return AdminContext(user=user, session_id=cached.session_id, scopes=cached.scopes)


__all__ = ["AdminContext", "GetCurrentAdmin"]
