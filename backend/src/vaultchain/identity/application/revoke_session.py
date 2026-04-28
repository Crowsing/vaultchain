"""RevokeSession + RevokeAllSessions use cases — AC-phase1-identity-004-07, -08.

Revocation is idempotent: an already-revoked session row stays revoked
without an extra event being captured. The access-token cache is
evicted via the secondary session index so the route doesn't need the
raw access token.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from vaultchain.identity.domain.events import SessionRevoked
from vaultchain.identity.domain.ports import AccessTokenCache, SessionRepository
from vaultchain.shared.domain.errors import NotFoundError
from vaultchain.shared.unit_of_work import AbstractUnitOfWork


@dataclass(frozen=True)
class RevokeSessionResult:
    revoked_session_ids: tuple[UUID, ...]


class RevokeSession:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        sessions: Callable[[Any], SessionRepository],
        cache: AccessTokenCache,
    ) -> None:
        self._uow_factory = uow_factory
        self._sessions = sessions
        self._cache = cache

    async def execute(self, *, session_id: UUID) -> RevokeSessionResult:
        async with self._uow_factory() as uow:
            sessions = self._sessions(uow.session)
            sess = await sessions.get_by_id(session_id)
            if sess is None:
                raise NotFoundError(details={"session_id": str(session_id)})
            if sess.revoked_at is not None:
                # Idempotent — no fresh event, no second cache eviction needed.
                await self._cache.evict_by_session(session_id)
                return RevokeSessionResult(revoked_session_ids=())

            sess.revoke(now=datetime.now(UTC))
            await sessions.update(sess)
            uow.add_event(SessionRevoked(aggregate_id=sess.id, user_id=sess.user_id))
            await uow.commit()

        await self._cache.evict_by_session(session_id)
        return RevokeSessionResult(revoked_session_ids=(session_id,))


class RevokeAllSessions:
    """Logout-everywhere — revoke every active session for a user.

    AC-08: emits one `SessionRevoked` event per session and evicts each
    session's cache entry. Already-revoked / expired sessions are skipped.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        sessions: Callable[[Any], SessionRepository],
        cache: AccessTokenCache,
    ) -> None:
        self._uow_factory = uow_factory
        self._sessions = sessions
        self._cache = cache

    async def execute(self, *, user_id: UUID) -> RevokeSessionResult:
        revoked: list[UUID] = []
        async with self._uow_factory() as uow:
            sessions = self._sessions(uow.session)
            now = datetime.now(UTC)
            for sess in await sessions.list_active_by_user_id(user_id):
                sess.revoke(now=now)
                await sessions.update(sess)
                uow.add_event(SessionRevoked(aggregate_id=sess.id, user_id=user_id))
                revoked.append(sess.id)
            await uow.commit()

        for sid in revoked:
            await self._cache.evict_by_session(sid)
        return RevokeSessionResult(revoked_session_ids=tuple(revoked))


__all__ = [
    "RevokeAllSessions",
    "RevokeSession",
    "RevokeSessionResult",
]
