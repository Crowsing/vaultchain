"""ConsumeMagicLink use case tests — AC-phase1-identity-002-05..08."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from tests.identity.fakes.fake_repositories import (
    InMemoryMagicLinkRepository,
    InMemoryTotpSecretRepository,
    InMemoryUserRepository,
)
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.consume_magic_link import (
    ConsumeMagicLink,
    MagicLinkConsumeResult,
)
from vaultchain.identity.domain.aggregates import (
    MagicLink,
    TotpSecret,
    User,
)
from vaultchain.identity.domain.errors import (
    MagicLinkAlreadyUsed,
    MagicLinkExpired,
    MagicLinkInvalid,
)
from vaultchain.identity.domain.events import MagicLinkConsumed
from vaultchain.identity.domain.value_objects import Email
from vaultchain.identity.infra.tokens.hashing import sha256_bytes


def _wire() -> (
    tuple[
        ConsumeMagicLink,
        FakeUnitOfWork,
        InMemoryUserRepository,
        InMemoryMagicLinkRepository,
        InMemoryTotpSecretRepository,
    ]
):
    users = InMemoryUserRepository()
    links = InMemoryMagicLinkRepository()
    totps = InMemoryTotpSecretRepository()
    uow = FakeUnitOfWork()
    use_case = ConsumeMagicLink(
        uow_factory=lambda: uow,
        users=lambda _s: users,
        magic_links=lambda _s: links,
        totp_secrets=lambda _s: totps,
    )
    return use_case, uow, users, links, totps


def _seed_user(users: InMemoryUserRepository, *, email: str = "user@x.io") -> User:
    e = Email(email)
    user = User.signup(email=e.value, email_hash=e.hash_blake2b())
    users.seed(user)
    return user


def _seed_link(
    links: InMemoryMagicLinkRepository,
    *,
    user_id: UUID,
    raw_token: str = "raw-tok",  # noqa: S107 — test fixture, not a password
    mode: str = "signup",
    expires_in: timedelta = timedelta(minutes=15),
    consumed: bool = False,
) -> MagicLink:
    now = datetime.now(UTC)
    link = MagicLink(
        id=uuid4(),
        user_id=user_id,
        token_hash=sha256_bytes(raw_token),
        mode=mode,  # type: ignore[arg-type]
        created_at=now,
        expires_at=now + expires_in,
        consumed_at=now if consumed else None,
    )
    links.seed(link)
    return link


@pytest.mark.asyncio
async def test_ac_05_consume_valid_link_returns_result_and_emits_event() -> None:
    use_case, uow, users, links, _totps = _wire()
    user = _seed_user(users)
    _seed_link(links, user_id=user.id, raw_token="raw-tok-1", mode="signup")

    result = await use_case.execute(raw_token="raw-tok-1", user_agent="ua", ip="192.0.2.1")

    assert isinstance(result, MagicLinkConsumeResult)
    assert result.user_id == user.id
    assert result.mode == "signup"
    # is_first_time = True iff TotpSecret repo has no row for this user
    assert result.is_first_time is True

    # Link's consumed_at is set
    persisted = await links.get_by_token_hash(sha256_bytes("raw-tok-1"))
    assert persisted is not None
    assert persisted.consumed_at is not None

    # Event captured
    assert any(
        isinstance(e, MagicLinkConsumed) and e.user_id == user.id and e.mode == "signup"
        for e in uow.captured_events
    )


@pytest.mark.asyncio
async def test_ac_05_returning_user_with_totp_enrolled_is_not_first_time() -> None:
    use_case, _uow, users, links, totps = _wire()
    user = _seed_user(users)
    user.verify_email()
    users.seed(user)
    totps.seed(
        TotpSecret(
            id=uuid4(),
            user_id=user.id,
            secret_encrypted=b"enc",
            backup_codes_hashed=[],
            enrolled_at=datetime.now(UTC),
        )
    )
    _seed_link(links, user_id=user.id, raw_token="ret-tok", mode="login")

    result = await use_case.execute(raw_token="ret-tok")

    assert result.is_first_time is False


@pytest.mark.asyncio
async def test_ac_06_consume_unknown_token_raises_invalid() -> None:
    use_case, _uow, users, _links, _totps = _wire()
    _seed_user(users)

    with pytest.raises(MagicLinkInvalid) as exc:
        await use_case.execute(raw_token="never-issued")

    assert exc.value.code == "identity.magic_link_invalid"
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_ac_07_consume_already_used_raises() -> None:
    use_case, _uow, users, links, _totps = _wire()
    user = _seed_user(users)
    _seed_link(links, user_id=user.id, raw_token="used-tok", consumed=True)

    with pytest.raises(MagicLinkAlreadyUsed) as exc:
        await use_case.execute(raw_token="used-tok")

    assert exc.value.code == "identity.magic_link_already_used"
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_ac_08_consume_expired_raises() -> None:
    use_case, _uow, users, links, _totps = _wire()
    user = _seed_user(users)
    _seed_link(
        links,
        user_id=user.id,
        raw_token="exp-tok",
        expires_in=timedelta(minutes=-1),
    )

    with pytest.raises(MagicLinkExpired) as exc:
        await use_case.execute(raw_token="exp-tok")

    assert exc.value.code == "identity.magic_link_expired"
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_ac_07_re_consume_does_not_modify_row_a_second_time() -> None:
    """On re-consume the row's consumed_at must NOT be re-touched."""
    use_case, _uow, users, links, _totps = _wire()
    user = _seed_user(users)
    link = _seed_link(links, user_id=user.id, raw_token="r-tok")
    # First consume succeeds
    await use_case.execute(raw_token="r-tok")
    persisted = await links.get_by_token_hash(sha256_bytes("r-tok"))
    assert persisted is not None
    first_consumed_at = persisted.consumed_at

    # Second attempt raises and DOES NOT bump consumed_at
    with pytest.raises(MagicLinkAlreadyUsed):
        await use_case.execute(raw_token="r-tok")
    persisted2 = await links.get_by_token_hash(sha256_bytes("r-tok"))
    assert persisted2 is not None
    assert persisted2.consumed_at == first_consumed_at
    # Aggregate id unchanged.
    assert persisted2.id == link.id
