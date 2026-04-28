"""RefreshSession use case tests — AC-phase1-identity-004-04, -05, -06."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.identity.fakes.fake_access_token_cache import FakeAccessTokenCache
from tests.identity.fakes.fake_repositories import InMemorySessionRepository
from tests.identity.fakes.fake_token_generator import DeterministicTokenGenerator
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.create_session import CreateSession
from vaultchain.identity.application.refresh_session import (
    RefreshSession,
    RefreshSessionResult,
)
from vaultchain.identity.domain.aggregates import Session
from vaultchain.identity.domain.errors import RefreshTokenInvalid
from vaultchain.identity.domain.events import SessionRefreshed
from vaultchain.identity.infra.tokens.hashing import sha256_bytes, sha256_hex


async def _seed_session() -> (
    tuple[
        str,
        InMemorySessionRepository,
        FakeAccessTokenCache,
        DeterministicTokenGenerator,
    ]
):
    """Helper: run CreateSession to seed a session, return its raw refresh token."""
    sessions = InMemorySessionRepository()
    cache = FakeAccessTokenCache()
    token_gen = DeterministicTokenGenerator()
    create_uow = FakeUnitOfWork()
    create = CreateSession(
        uow_factory=lambda: create_uow,
        sessions=lambda _s: sessions,
        cache=cache,
        token_gen=token_gen,
    )
    result = await create.execute(user_id=uuid4(), user_agent="ua", ip="10.0.0.1")
    return result.refresh_token_raw, sessions, cache, token_gen


@pytest.mark.asyncio
async def test_ac_04_refresh_rotates_token_and_invalidates_old() -> None:
    refresh_raw, sessions, cache, token_gen = await _seed_session()

    refresh_uow = FakeUnitOfWork()
    refresh = RefreshSession(
        uow_factory=lambda: refresh_uow,
        sessions=lambda _s: sessions,
        cache=cache,
        token_gen=token_gen,
    )
    out = await refresh.execute(refresh_token_raw=refresh_raw)

    assert isinstance(out, RefreshSessionResult)
    # Old refresh token no longer matches a row.
    assert await sessions.get_by_refresh_token_hash(sha256_bytes(refresh_raw)) is None
    # New refresh token does.
    assert await sessions.get_by_refresh_token_hash(sha256_bytes(out.refresh_token_raw)) is not None
    # New access token is now in the cache.
    assert await cache.get(sha256_hex(out.access_token_raw)) is not None
    # Refreshed event captured (new UoW only).
    assert any(isinstance(e, SessionRefreshed) for e in refresh_uow.captured_events)


@pytest.mark.asyncio
async def test_ac_04_session_id_preserved_across_refresh() -> None:
    refresh_raw, sessions, cache, token_gen = await _seed_session()

    [original] = list(sessions._by_id.values())
    original_id = original.id

    refresh = RefreshSession(
        uow_factory=lambda: FakeUnitOfWork(),
        sessions=lambda _s: sessions,
        cache=cache,
        token_gen=token_gen,
    )
    out = await refresh.execute(refresh_token_raw=refresh_raw)
    assert out.session_id == original_id


@pytest.mark.asyncio
async def test_ac_05_refresh_with_unknown_token_raises_invalid() -> None:
    sessions = InMemorySessionRepository()
    cache = FakeAccessTokenCache()
    token_gen = DeterministicTokenGenerator()
    refresh = RefreshSession(
        uow_factory=lambda: FakeUnitOfWork(),
        sessions=lambda _s: sessions,
        cache=cache,
        token_gen=token_gen,
    )
    with pytest.raises(RefreshTokenInvalid) as exc:
        await refresh.execute(refresh_token_raw="vc_rt_does_not_exist")
    assert exc.value.code == "identity.refresh_token_invalid"
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_ac_06_refresh_revoked_session_raises_invalid() -> None:
    refresh_raw, sessions, cache, token_gen = await _seed_session()
    # Mark the seeded session as revoked.
    [s] = list(sessions._by_id.values())
    s.revoke()
    sessions._by_id[s.id] = s

    refresh = RefreshSession(
        uow_factory=lambda: FakeUnitOfWork(),
        sessions=lambda _s: sessions,
        cache=cache,
        token_gen=token_gen,
    )
    with pytest.raises(RefreshTokenInvalid):
        await refresh.execute(refresh_token_raw=refresh_raw)


@pytest.mark.asyncio
async def test_ac_06_refresh_expired_session_raises_invalid() -> None:
    sessions = InMemorySessionRepository()
    cache = FakeAccessTokenCache()
    token_gen = DeterministicTokenGenerator()
    user_id = uuid4()
    raw = "vc_rt_expired"
    now = datetime.now(UTC)
    sessions.seed(
        Session(
            id=uuid4(),
            user_id=user_id,
            refresh_token_hash=sha256_bytes(raw),
            created_at=now - timedelta(days=31),
            last_used_at=now - timedelta(days=31),
            expires_at=now - timedelta(seconds=1),  # expired
        )
    )
    refresh = RefreshSession(
        uow_factory=lambda: FakeUnitOfWork(),
        sessions=lambda _s: sessions,
        cache=cache,
        token_gen=token_gen,
    )
    with pytest.raises(RefreshTokenInvalid):
        await refresh.execute(refresh_token_raw=raw)


@pytest.mark.asyncio
async def test_ac_04_old_access_token_evicted_from_cache_on_refresh() -> None:
    refresh_raw, sessions, cache, token_gen = await _seed_session()
    # The access-token cache has one entry from CreateSession; capture its key.
    [old_key] = list(cache._store.keys())

    refresh = RefreshSession(
        uow_factory=lambda: FakeUnitOfWork(),
        sessions=lambda _s: sessions,
        cache=cache,
        token_gen=token_gen,
    )
    await refresh.execute(refresh_token_raw=refresh_raw)
    assert old_key not in cache._store
