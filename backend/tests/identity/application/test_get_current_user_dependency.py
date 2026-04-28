"""`GetCurrentUser` and `CsrfGuard` tests — AC-phase1-identity-004-03, -09."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from tests.identity.fakes.fake_access_token_cache import FakeAccessTokenCache
from tests.identity.fakes.fake_repositories import InMemoryUserRepository
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.delivery.dependencies import (
    CsrfGuard,
    GetCurrentUser,
    UserContext,
)
from vaultchain.identity.domain.aggregates import User, UserStatus
from vaultchain.identity.domain.errors import (
    CsrfFailed,
    Unauthenticated,
    UserLocked,
)
from vaultchain.identity.domain.ports import CachedAccessToken
from vaultchain.identity.domain.value_objects import Email
from vaultchain.identity.infra.tokens.cookies import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
)
from vaultchain.identity.infra.tokens.hashing import sha256_hex


@dataclass
class _FakeRequest:
    cookies: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    method: str = "GET"


def _verified_user() -> User:
    e = Email("dep@example.com")
    user = User.signup(email=e.value, email_hash=e.hash_blake2b())
    user.pull_events()
    user.status = UserStatus.VERIFIED
    return user


# ----------------------------- GetCurrentUser ----------------------------- #


@pytest.mark.asyncio
async def test_ac_03_valid_token_returns_user_context() -> None:
    user = _verified_user()
    users = InMemoryUserRepository()
    users.seed(user)
    cache = FakeAccessTokenCache()
    sid = uuid4()
    raw = "vc_at_VALID"
    await cache.set(
        sha256_hex(raw),
        CachedAccessToken(
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            scopes=("user",),
            session_id=sid,
        ),
    )
    dep = GetCurrentUser(
        cache=cache,
        uow_factory=lambda: FakeUnitOfWork(),
        users=lambda _s: users,
    )
    ctx = await dep(_FakeRequest(cookies={ACCESS_COOKIE_NAME: raw}))
    assert isinstance(ctx, UserContext)
    assert ctx.user.id == user.id
    assert ctx.session_id == sid
    assert ctx.scopes == ("user",)


@pytest.mark.asyncio
async def test_ac_03_missing_cookie_raises_unauthenticated() -> None:
    dep = GetCurrentUser(
        cache=FakeAccessTokenCache(),
        uow_factory=lambda: FakeUnitOfWork(),
        users=lambda _s: InMemoryUserRepository(),
    )
    with pytest.raises(Unauthenticated):
        await dep(_FakeRequest(cookies={}))


@pytest.mark.asyncio
async def test_ac_03_expired_or_unknown_token_raises_unauthenticated() -> None:
    dep = GetCurrentUser(
        cache=FakeAccessTokenCache(),  # empty
        uow_factory=lambda: FakeUnitOfWork(),
        users=lambda _s: InMemoryUserRepository(),
    )
    with pytest.raises(Unauthenticated):
        await dep(_FakeRequest(cookies={ACCESS_COOKIE_NAME: "vc_at_unknown"}))


@pytest.mark.asyncio
async def test_ac_03_locked_user_raises_user_locked() -> None:
    user = _verified_user()
    user.status = UserStatus.LOCKED
    user.locked_until = datetime.now(UTC) + timedelta(minutes=10)
    users = InMemoryUserRepository()
    users.seed(user)
    cache = FakeAccessTokenCache()
    raw = "vc_at_LOCKED"
    await cache.set(
        sha256_hex(raw),
        CachedAccessToken(
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            scopes=("user",),
            session_id=uuid4(),
        ),
    )
    dep = GetCurrentUser(
        cache=cache,
        uow_factory=lambda: FakeUnitOfWork(),
        users=lambda _s: users,
    )
    with pytest.raises(UserLocked):
        await dep(_FakeRequest(cookies={ACCESS_COOKIE_NAME: raw}))


@pytest.mark.asyncio
async def test_ac_03_user_missing_after_cache_hit_raises_unauthenticated() -> None:
    """Defensive: cache had a stale entry pointing to a nuked user row."""
    cache = FakeAccessTokenCache()
    raw = "vc_at_GHOST"
    await cache.set(
        sha256_hex(raw),
        CachedAccessToken(
            user_id=uuid4(),
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            scopes=("user",),
            session_id=uuid4(),
        ),
    )
    dep = GetCurrentUser(
        cache=cache,
        uow_factory=lambda: FakeUnitOfWork(),
        users=lambda _s: InMemoryUserRepository(),  # empty
    )
    with pytest.raises(Unauthenticated):
        await dep(_FakeRequest(cookies={ACCESS_COOKIE_NAME: raw}))


# -------------------------------- CsrfGuard -------------------------------- #


@pytest.mark.asyncio
async def test_ac_09_csrf_passes_get_through() -> None:
    guard = CsrfGuard()
    await guard(_FakeRequest(method="GET"))  # no exception
    await guard(_FakeRequest(method="HEAD"))
    await guard(_FakeRequest(method="OPTIONS"))


@pytest.mark.asyncio
async def test_ac_09_csrf_post_with_matching_cookie_and_header_passes() -> None:
    guard = CsrfGuard()
    await guard(
        _FakeRequest(
            method="POST",
            cookies={CSRF_COOKIE_NAME: "csrf-token-value"},
            headers={"X-CSRF-Token": "csrf-token-value"},
        )
    )


@pytest.mark.asyncio
async def test_ac_09_csrf_post_missing_header_raises() -> None:
    guard = CsrfGuard()
    with pytest.raises(CsrfFailed) as exc:
        await guard(
            _FakeRequest(
                method="POST",
                cookies={CSRF_COOKIE_NAME: "x"},
                headers={},
            )
        )
    assert exc.value.code == "identity.csrf_failed"
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_ac_09_csrf_post_mismatched_token_raises() -> None:
    guard = CsrfGuard()
    with pytest.raises(CsrfFailed):
        await guard(
            _FakeRequest(
                method="POST",
                cookies={CSRF_COOKIE_NAME: "abc"},
                headers={"X-CSRF-Token": "xyz"},
            )
        )


@pytest.mark.asyncio
async def test_ac_09_csrf_put_patch_delete_all_protected() -> None:
    guard = CsrfGuard()
    for method in ("PUT", "PATCH", "DELETE"):
        with pytest.raises(CsrfFailed):
            await guard(_FakeRequest(method=method))


@pytest.mark.asyncio
async def test_ac_09_csrf_header_match_is_case_insensitive_on_name() -> None:
    """Headers in HTTP/1.1 are case-insensitive — ensure the guard reflects that."""
    guard = CsrfGuard()
    await guard(
        _FakeRequest(
            method="POST",
            cookies={CSRF_COOKIE_NAME: "v"},
            headers={"x-csrf-token": "v"},
        )
    )
