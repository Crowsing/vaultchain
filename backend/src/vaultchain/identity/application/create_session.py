"""CreateSession use case — AC-phase1-identity-004-01.

Creates a session row + access-token cache entry after a successful TOTP
verify. Returns the raw access/refresh/CSRF tokens once for the route
layer to set as cookies; subsequent reads of the session row never
return raw tokens.

The `refresh_token_hash` column stores `sha256(refresh_token_raw)` — a
deterministic 32-byte digest. argon2id is unnecessary here because the
refresh token has 32 bytes of cryptographic randomness; salting would
prevent the O(1) lookup the refresh path needs (~50ms argon2 verify
on every refresh would defeat the cache's purpose).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from vaultchain.identity.domain.aggregates import Session
from vaultchain.identity.domain.events import SessionCreated
from vaultchain.identity.domain.ports import (
    AccessTokenCache,
    CachedAccessToken,
    RefreshTokenGenerator,
    SessionRepository,
)
from vaultchain.identity.infra.tokens.hashing import sha256_bytes, sha256_hex
from vaultchain.shared.unit_of_work import AbstractUnitOfWork

#: Refresh-token lifetime per architecture-decisions Section 4.
REFRESH_TOKEN_TTL = timedelta(days=30)
#: Access-token lifetime per architecture-decisions Section 4.
ACCESS_TOKEN_TTL = timedelta(minutes=15)
#: V1 user-session scope; Phase-3 admin scopes layer on top.
DEFAULT_SCOPES: tuple[str, ...] = ("user",)


@dataclass(frozen=True)
class CreateSessionResult:
    """Raw tokens returned ONCE for the route layer to set as cookies."""

    access_token_raw: str
    refresh_token_raw: str
    csrf_token_raw: str
    expires_at: datetime
    session_id: UUID


class CreateSession:
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

    async def execute(
        self,
        *,
        user_id: UUID,
        user_agent: str = "",
        ip: str | None = None,
    ) -> CreateSessionResult:
        access_raw = self._token_gen.generate_access_token()
        refresh_raw = self._token_gen.generate_refresh_token()
        csrf_raw = self._token_gen.generate_csrf_token()

        now = datetime.now(UTC)
        expires_at = now + REFRESH_TOKEN_TTL
        access_expires_at = now + ACCESS_TOKEN_TTL
        session_id = uuid4()

        session = Session(
            id=session_id,
            user_id=user_id,
            refresh_token_hash=sha256_bytes(refresh_raw),
            created_at=now,
            last_used_at=now,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_inet=ip,
        )

        async with self._uow_factory() as uow:
            await self._sessions(uow.session).add(session)
            uow.add_event(SessionCreated(aggregate_id=session_id, user_id=user_id))
            await uow.commit()

        # Cache write happens AFTER the UoW commit so we never advertise a
        # session via the cache that's not in the DB. If Redis goes down
        # between the commit and this set, the access token is unusable
        # (the dependency will reject it) but a refresh round-trip recovers.
        await self._cache.set(
            sha256_hex(access_raw),
            CachedAccessToken(
                user_id=user_id,
                expires_at=access_expires_at,
                scopes=DEFAULT_SCOPES,
                session_id=session_id,
            ),
        )

        return CreateSessionResult(
            access_token_raw=access_raw,
            refresh_token_raw=refresh_raw,
            csrf_token_raw=csrf_raw,
            expires_at=expires_at,
            session_id=session_id,
        )


__all__ = [
    "ACCESS_TOKEN_TTL",
    "DEFAULT_SCOPES",
    "REFRESH_TOKEN_TTL",
    "CreateSession",
    "CreateSessionResult",
]
