"""RefreshSession use case — AC-phase1-identity-004-04, -05, -06.

Rotates the refresh token and mints a fresh access token + CSRF cookie.
The session row keeps the same id; only the hash + last_used_at change,
preserving audit continuity. ``RefreshTokenInvalid`` is raised
indistinguishably for unknown / revoked / expired tokens to avoid
information leakage.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from vaultchain.identity.application.create_session import (
    ACCESS_TOKEN_TTL,
    DEFAULT_SCOPES,
    REFRESH_TOKEN_TTL,
)
from vaultchain.identity.domain.errors import RefreshTokenInvalid
from vaultchain.identity.domain.events import SessionRefreshed
from vaultchain.identity.domain.ports import (
    AccessTokenCache,
    CachedAccessToken,
    RefreshTokenGenerator,
    SessionRepository,
)
from vaultchain.identity.infra.tokens.hashing import sha256_bytes, sha256_hex
from vaultchain.shared.unit_of_work import AbstractUnitOfWork


@dataclass(frozen=True)
class RefreshSessionResult:
    access_token_raw: str
    refresh_token_raw: str
    csrf_token_raw: str
    expires_at: datetime
    session_id: UUID


class RefreshSession:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractUnitOfWork],
        sessions: Callable[[Any], SessionRepository],
        cache: AccessTokenCache,
        token_gen: RefreshTokenGenerator,
    ) -> None:
        self._uow_factory = uow_factory
        self._sessions = sessions
        self._cache = cache
        self._token_gen = token_gen

    async def execute(self, *, refresh_token_raw: str) -> RefreshSessionResult:
        old_hash = sha256_bytes(refresh_token_raw)
        async with self._uow_factory() as uow:
            sessions = self._sessions(uow.session)
            sess = await sessions.get_by_refresh_token_hash(old_hash)
            now = datetime.now(UTC)
            if sess is None or sess.revoked_at is not None or sess.expires_at <= now:
                # AC-05/06 — same code regardless of cause.
                raise RefreshTokenInvalid()

            new_access = self._token_gen.generate_access_token()
            new_refresh = self._token_gen.generate_refresh_token()
            new_csrf = self._token_gen.generate_csrf_token()

            sess.refresh_token_hash = sha256_bytes(new_refresh)
            sess.last_used_at = now
            sess.expires_at = now + REFRESH_TOKEN_TTL
            sess.version += 1
            await sessions.update(sess)

            uow.add_event(SessionRefreshed(aggregate_id=sess.id, user_id=sess.user_id))
            await uow.commit()

        # Evict the old access token (if any) and prime the cache with the new
        # one. Done after the DB commit so the cache never advertises a state
        # the DB doesn't agree with.
        await self._cache.evict_by_session(sess.id)
        access_expires_at = now + ACCESS_TOKEN_TTL
        await self._cache.set(
            sha256_hex(new_access),
            CachedAccessToken(
                user_id=sess.user_id,
                expires_at=access_expires_at,
                scopes=DEFAULT_SCOPES,
                session_id=sess.id,
            ),
        )

        return RefreshSessionResult(
            access_token_raw=new_access,
            refresh_token_raw=new_refresh,
            csrf_token_raw=new_csrf,
            expires_at=sess.expires_at,
            session_id=sess.id,
        )


# Pull `timedelta` so future test-only imports don't strip the symbol.
_ = timedelta


__all__ = ["RefreshSession", "RefreshSessionResult"]
