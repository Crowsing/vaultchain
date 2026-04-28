"""RevokeSession + RevokeAllSessions tests — AC-phase1-identity-004-07, -08."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.identity.fakes.fake_access_token_cache import FakeAccessTokenCache
from tests.identity.fakes.fake_repositories import InMemorySessionRepository
from tests.identity.fakes.fake_token_generator import DeterministicTokenGenerator
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.create_session import CreateSession
from vaultchain.identity.application.revoke_session import (
    RevokeAllSessions,
    RevokeSession,
)
from vaultchain.identity.domain.events import SessionRevoked
from vaultchain.identity.infra.tokens.hashing import sha256_hex


async def _create(user_id: object, sessions: object, cache: object, gen: object) -> object:
    create_uow = FakeUnitOfWork()
    create = CreateSession(
        uow_factory=lambda: create_uow,
        sessions=lambda _s: sessions,  # type: ignore[arg-type, return-value]
        cache=cache,  # type: ignore[arg-type]
        token_gen=gen,  # type: ignore[arg-type]
    )
    return await create.execute(user_id=user_id)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_ac_07_revoke_evicts_cache_and_emits_event() -> None:
    sessions = InMemorySessionRepository()
    cache = FakeAccessTokenCache()
    gen = DeterministicTokenGenerator()
    user_id = uuid4()
    seeded = await _create(user_id, sessions, cache, gen)

    revoke_uow = FakeUnitOfWork()
    revoke = RevokeSession(
        uow_factory=lambda: revoke_uow,
        sessions=lambda _s: sessions,
        cache=cache,
    )
    out = await revoke.execute(session_id=seeded.session_id)  # type: ignore[attr-defined]

    persisted = await sessions.get_by_id(seeded.session_id)  # type: ignore[attr-defined]
    assert persisted is not None
    assert persisted.revoked_at is not None
    assert any(isinstance(e, SessionRevoked) for e in revoke_uow.captured_events)
    # Access-token cache evicted by session id
    assert await cache.get(sha256_hex(seeded.access_token_raw)) is None  # type: ignore[attr-defined]
    assert seeded.session_id in out.revoked_session_ids  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_ac_07_revoke_idempotent_on_already_revoked() -> None:
    sessions = InMemorySessionRepository()
    cache = FakeAccessTokenCache()
    gen = DeterministicTokenGenerator()
    seeded = await _create(uuid4(), sessions, cache, gen)

    first_uow = FakeUnitOfWork()
    revoke = RevokeSession(
        uow_factory=lambda: first_uow,
        sessions=lambda _s: sessions,
        cache=cache,
    )
    await revoke.execute(session_id=seeded.session_id)  # type: ignore[attr-defined]

    # Second revoke — same session — must not emit a fresh event or fail.
    second_uow = FakeUnitOfWork()
    revoke2 = RevokeSession(
        uow_factory=lambda: second_uow,
        sessions=lambda _s: sessions,
        cache=cache,
    )
    out = await revoke2.execute(session_id=seeded.session_id)  # type: ignore[attr-defined]

    assert second_uow.captured_events == []  # no fresh event
    assert second_uow.committed is False
    assert out.revoked_session_ids == ()


@pytest.mark.asyncio
async def test_ac_08_revoke_all_sessions_evicts_each() -> None:
    sessions = InMemorySessionRepository()
    cache = FakeAccessTokenCache()
    gen = DeterministicTokenGenerator()
    user_id = uuid4()
    seeded_a = await _create(user_id, sessions, cache, gen)
    seeded_b = await _create(user_id, sessions, cache, gen)
    seeded_other_user = await _create(uuid4(), sessions, cache, gen)

    uow = FakeUnitOfWork()
    revoke_all = RevokeAllSessions(
        uow_factory=lambda: uow,
        sessions=lambda _s: sessions,
        cache=cache,
    )
    out = await revoke_all.execute(user_id=user_id)

    assert seeded_a.session_id in out.revoked_session_ids  # type: ignore[attr-defined]
    assert seeded_b.session_id in out.revoked_session_ids  # type: ignore[attr-defined]
    # The other user's session is untouched
    assert seeded_other_user.session_id not in out.revoked_session_ids  # type: ignore[attr-defined]
    other = await sessions.get_by_id(seeded_other_user.session_id)  # type: ignore[attr-defined]
    assert other is not None
    assert other.revoked_at is None
    # One event per revoked session
    assert sum(1 for e in uow.captured_events if isinstance(e, SessionRevoked)) == 2
    # Caches evicted for revoked sessions only
    assert await cache.get(sha256_hex(seeded_a.access_token_raw)) is None  # type: ignore[attr-defined]
    assert await cache.get(sha256_hex(seeded_b.access_token_raw)) is None  # type: ignore[attr-defined]
    assert await cache.get(sha256_hex(seeded_other_user.access_token_raw)) is not None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_revoke_unknown_session_raises_not_found() -> None:
    from vaultchain.shared.domain.errors import NotFoundError

    sessions = InMemorySessionRepository()
    cache = FakeAccessTokenCache()
    revoke = RevokeSession(
        uow_factory=lambda: FakeUnitOfWork(),
        sessions=lambda _s: sessions,
        cache=cache,
    )
    with pytest.raises(NotFoundError):
        await revoke.execute(session_id=uuid4())
