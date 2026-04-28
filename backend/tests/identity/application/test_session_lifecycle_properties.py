"""Hypothesis property tests for the session lifecycle.

Drives long random sequences of (Create, Refresh, Revoke) operations on
a single user; asserts:

  - The refresh-token hash always rotates on a successful refresh.
  - Revoked sessions never become active again.
  - At any moment, every active session row has a *unique* refresh-token
    hash (the table's UNIQUE constraint mirrors this; the fake repo
    doesn't enforce it, so the property guards behavioural correctness).
  - The cache contains an entry only for sessions that are still active.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.identity.fakes.fake_access_token_cache import FakeAccessTokenCache
from tests.identity.fakes.fake_repositories import InMemorySessionRepository
from tests.identity.fakes.fake_token_generator import DeterministicTokenGenerator
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.create_session import CreateSession
from vaultchain.identity.application.refresh_session import RefreshSession
from vaultchain.identity.application.revoke_session import RevokeSession
from vaultchain.identity.domain.errors import RefreshTokenInvalid
from vaultchain.identity.infra.tokens.hashing import sha256_hex

pytestmark = pytest.mark.property


class _Op(str, Enum):
    CREATE = "create"
    REFRESH = "refresh"
    REVOKE = "revoke"


@given(
    ops=st.lists(
        st.sampled_from(list(_Op)),
        min_size=1,
        max_size=15,
    )
)
@settings(max_examples=40, deadline=None)
def test_session_lifecycle_invariants_hold_for_random_sequences(ops: list[_Op]) -> None:
    async def run() -> None:
        sessions_repo = InMemorySessionRepository()
        cache = FakeAccessTokenCache()
        gen = DeterministicTokenGenerator()
        user_id = uuid4()

        # Track which refresh tokens are "live" — we have to keep them around
        # because the only way to refresh is by raw token.
        live_refresh_tokens: list[tuple[str, object]] = []  # (raw_refresh, session_id)

        for op in ops:
            if op is _Op.CREATE:
                create = CreateSession(
                    uow_factory=lambda: FakeUnitOfWork(),
                    sessions=lambda _s: sessions_repo,
                    cache=cache,
                    token_gen=gen,
                )
                r = await create.execute(user_id=user_id)
                live_refresh_tokens.append((r.refresh_token_raw, r.session_id))

            elif op is _Op.REFRESH and live_refresh_tokens:
                idx = len(live_refresh_tokens) - 1  # refresh the most recent
                old_raw, sid = live_refresh_tokens[idx]
                refresh = RefreshSession(
                    uow_factory=lambda: FakeUnitOfWork(),
                    sessions=lambda _s: sessions_repo,
                    cache=cache,
                    token_gen=gen,
                )
                try:
                    r = await refresh.execute(refresh_token_raw=old_raw)
                except RefreshTokenInvalid:
                    # Session was revoked since being added to live list.
                    live_refresh_tokens.pop(idx)
                    continue
                # rotation invariant: new raw token != old raw token
                assert r.refresh_token_raw != old_raw
                live_refresh_tokens[idx] = (r.refresh_token_raw, sid)

            elif op is _Op.REVOKE and live_refresh_tokens:
                idx = len(live_refresh_tokens) - 1
                _, sid = live_refresh_tokens.pop(idx)
                revoke = RevokeSession(
                    uow_factory=lambda: FakeUnitOfWork(),
                    sessions=lambda _s: sessions_repo,
                    cache=cache,
                )
                await revoke.execute(session_id=sid)
                # Revoked invariant: session row's revoked_at is set.
                row = await sessions_repo.get_by_id(sid)
                assert row is not None
                assert row.revoked_at is not None

            # ---- after every op, assert global invariants ----

            # Active session refresh-token hashes must be unique.
            actives = await sessions_repo.list_active_by_user_id(user_id)
            hashes = [bytes(s.refresh_token_hash) for s in actives]
            assert len(hashes) == len(set(hashes))

            # Cache entries should only exist for live sessions of this user.
            active_ids = {s.id for s in actives}
            cached_session_ids = {p.session_id for p in cache._store.values()}
            for sid in cached_session_ids:
                # cached session id must correspond to an active session
                still_active = await sessions_repo.list_active_by_user_id(user_id)
                assert sid in active_ids or any(s.user_id != user_id for s in still_active)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


@given(refresh_count=st.integers(min_value=1, max_value=8))
@settings(max_examples=10, deadline=None)
def test_refresh_always_rotates_hash(refresh_count: int) -> None:
    """Every successful refresh produces a fresh refresh-token hash."""

    async def run() -> None:
        sessions_repo = InMemorySessionRepository()
        cache = FakeAccessTokenCache()
        gen = DeterministicTokenGenerator()
        create = CreateSession(
            uow_factory=lambda: FakeUnitOfWork(),
            sessions=lambda _s: sessions_repo,
            cache=cache,
            token_gen=gen,
        )
        seeded = await create.execute(user_id=uuid4())
        observed_hashes: set[bytes] = set()
        observed_hashes.add(
            (await sessions_repo.get_by_id(seeded.session_id)).refresh_token_hash  # type: ignore[union-attr]
        )

        raw = seeded.refresh_token_raw
        for _ in range(refresh_count):
            refresh = RefreshSession(
                uow_factory=lambda: FakeUnitOfWork(),
                sessions=lambda _s: sessions_repo,
                cache=cache,
                token_gen=gen,
            )
            r = await refresh.execute(refresh_token_raw=raw)
            new_hash = (await sessions_repo.get_by_id(seeded.session_id)).refresh_token_hash  # type: ignore[union-attr]
            assert new_hash not in observed_hashes
            observed_hashes.add(new_hash)
            raw = r.refresh_token_raw

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


@given(create_count=st.integers(min_value=1, max_value=6))
@settings(max_examples=8, deadline=None)
def test_revoked_sessions_stay_revoked(create_count: int) -> None:
    """No matter the create count, revoking each turns it terminal."""

    async def run() -> None:
        sessions_repo = InMemorySessionRepository()
        cache = FakeAccessTokenCache()
        gen = DeterministicTokenGenerator()
        user_id = uuid4()
        seeded = []
        for _ in range(create_count):
            create = CreateSession(
                uow_factory=lambda: FakeUnitOfWork(),
                sessions=lambda _s: sessions_repo,
                cache=cache,
                token_gen=gen,
            )
            seeded.append(await create.execute(user_id=user_id))

        for s in seeded:
            revoke = RevokeSession(
                uow_factory=lambda: FakeUnitOfWork(),
                sessions=lambda _s: sessions_repo,
                cache=cache,
            )
            await revoke.execute(session_id=s.session_id)
            row = await sessions_repo.get_by_id(s.session_id)
            assert row is not None
            assert row.revoked_at is not None
            # Cache entry gone.
            assert await cache.get(sha256_hex(s.access_token_raw)) is None

        # No active sessions remain.
        actives = await sessions_repo.list_active_by_user_id(user_id)
        assert actives == []

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()
