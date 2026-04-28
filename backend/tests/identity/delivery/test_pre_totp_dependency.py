"""Tests for `get_pre_totp_user` dependency — AC-phase1-identity-005-05."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from tests.identity.fakes.fake_pre_totp_cache import FakePreTotpTokenCache
from vaultchain.identity.delivery.dependencies.pre_totp import make_get_pre_totp_user
from vaultchain.identity.domain.errors import PreTotpTokenInvalid
from vaultchain.identity.domain.ports import PreTotpIntent, PreTotpPayload
from vaultchain.identity.infra.tokens.hashing import sha256_hex


@dataclass
class _FakeRequest:
    headers: dict[str, str] = field(default_factory=dict)


@pytest.mark.asyncio
async def test_resolves_user_id_when_intent_matches() -> None:
    cache = FakePreTotpTokenCache()
    user_id = uuid4()
    raw = "tok-1234"
    await cache.set(sha256_hex(raw), PreTotpPayload(user_id=user_id, intent=PreTotpIntent.ENROLL))

    dep = make_get_pre_totp_user(cache=cache, intent=PreTotpIntent.ENROLL)
    resolved = await dep(_FakeRequest(headers={"Authorization": f"Bearer {raw}"}))
    assert resolved == user_id


@pytest.mark.asyncio
async def test_missing_bearer_raises_pre_totp_token_invalid() -> None:
    cache = FakePreTotpTokenCache()
    dep = make_get_pre_totp_user(cache=cache, intent=PreTotpIntent.ENROLL)

    with pytest.raises(PreTotpTokenInvalid) as exc:
        await dep(_FakeRequest(headers={}))
    assert exc.value.code == "identity.pre_totp_token_invalid"
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_unknown_token_raises() -> None:
    cache = FakePreTotpTokenCache()
    dep = make_get_pre_totp_user(cache=cache, intent=PreTotpIntent.ENROLL)

    with pytest.raises(PreTotpTokenInvalid):
        await dep(_FakeRequest(headers={"Authorization": "Bearer unknown"}))


@pytest.mark.asyncio
async def test_intent_mismatch_raises() -> None:
    cache = FakePreTotpTokenCache()
    user_id = uuid4()
    raw = "tok-mismatch"
    await cache.set(sha256_hex(raw), PreTotpPayload(user_id=user_id, intent=PreTotpIntent.ENROLL))
    # Dependency wired for CHALLENGE but cached as ENROLL.
    dep = make_get_pre_totp_user(cache=cache, intent=PreTotpIntent.CHALLENGE)

    with pytest.raises(PreTotpTokenInvalid):
        await dep(_FakeRequest(headers={"Authorization": f"Bearer {raw}"}))


@pytest.mark.asyncio
async def test_lowercase_bearer_scheme_accepted() -> None:
    cache = FakePreTotpTokenCache()
    user_id = uuid4()
    raw = "tok-case"
    await cache.set(sha256_hex(raw), PreTotpPayload(user_id=user_id, intent=PreTotpIntent.ENROLL))

    dep = make_get_pre_totp_user(cache=cache, intent=PreTotpIntent.ENROLL)
    resolved = await dep(_FakeRequest(headers={"authorization": f"bearer {raw}"}))
    assert resolved == user_id
