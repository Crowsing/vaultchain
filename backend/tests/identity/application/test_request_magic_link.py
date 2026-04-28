"""RequestMagicLink use case tests — AC-phase1-identity-002-01..04."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.identity.fakes.fake_email_sender import FakeEmailSender
from tests.identity.fakes.fake_magic_link_token_generator import (
    DeterministicMagicLinkTokenGenerator,
)
from tests.identity.fakes.fake_repositories import (
    InMemoryMagicLinkRepository,
    InMemoryUserRepository,
)
from tests.identity.fakes.fake_uow import FakeUnitOfWork
from vaultchain.identity.application.request_magic_link import (
    MAGIC_LINK_TTL,
    RequestMagicLink,
    RequestMagicLinkResult,
)
from vaultchain.identity.domain.aggregates import User, UserStatus
from vaultchain.identity.domain.errors import UserLocked
from vaultchain.identity.domain.events import MagicLinkRequested, UserSignedUp
from vaultchain.identity.domain.value_objects import Email


def _wire() -> (
    tuple[
        RequestMagicLink,
        FakeUnitOfWork,
        InMemoryUserRepository,
        InMemoryMagicLinkRepository,
        FakeEmailSender,
        DeterministicMagicLinkTokenGenerator,
    ]
):
    users = InMemoryUserRepository()
    links = InMemoryMagicLinkRepository()
    emails = FakeEmailSender()
    tok_gen = DeterministicMagicLinkTokenGenerator()
    uow = FakeUnitOfWork()
    use_case = RequestMagicLink(
        uow_factory=lambda: uow,
        users=lambda _s: users,
        magic_links=lambda _s: links,
        emails=emails,
        token_gen=tok_gen,
    )
    return use_case, uow, users, links, emails, tok_gen


@pytest.mark.asyncio
async def test_ac_01_signup_new_email_creates_user_and_link() -> None:
    use_case, uow, users, links, emails, _gen = _wire()
    before = datetime.now(UTC)

    result = await use_case.execute(email="new@x.io", mode="signup")
    after = datetime.now(UTC)

    assert isinstance(result, RequestMagicLinkResult)
    assert result.accepted is True

    user = await users.get_by_email("new@x.io")
    assert user is not None
    assert user.status is UserStatus.UNVERIFIED

    # Magic link persisted, mode + 15-min expiry.
    link = next(iter(links._by_id.values()))
    assert link.user_id == user.id
    assert link.mode == "signup"
    assert before + MAGIC_LINK_TTL <= link.expires_at <= after + MAGIC_LINK_TTL
    assert link.consumed_at is None

    # EmailSender called with raw token.
    assert len(emails.sent) == 1
    sent = emails.sent[0]
    assert sent.to_email == "new@x.io"
    assert sent.mode == "signup"
    assert isinstance(sent.raw_token, str)
    assert len(sent.raw_token) > 0

    # Events captured: signup gets UserSignedUp + MagicLinkRequested.
    assert any(isinstance(e, UserSignedUp) for e in uow.captured_events)
    assert any(isinstance(e, MagicLinkRequested) for e in uow.captured_events)


@pytest.mark.asyncio
async def test_ac_02_login_existing_verified_user_creates_link_no_new_user() -> None:
    use_case, _uow, users, links, emails, _gen = _wire()
    e = Email("returning@x.io")
    existing = User.signup(email=e.value, email_hash=e.hash_blake2b())
    existing.verify_email()
    users.seed(existing)
    pre_count = len(users._by_id)

    result = await use_case.execute(email="returning@x.io", mode="login")
    assert result.accepted is True

    # No new user
    assert len(users._by_id) == pre_count

    # Magic link present with mode=login
    link = next(iter(links._by_id.values()))
    assert link.user_id == existing.id
    assert link.mode == "login"

    assert len(emails.sent) == 1
    assert emails.sent[0].mode == "login"


@pytest.mark.asyncio
async def test_ac_03_locked_user_rejected() -> None:
    use_case, _uow, users, links, emails, _gen = _wire()
    e = Email("locked@x.io")
    user = User.signup(email=e.value, email_hash=e.hash_blake2b())
    user.verify_email()
    user.locked_until = datetime.now(UTC) + timedelta(minutes=15)
    user.status = UserStatus.LOCKED
    users.seed(user)

    with pytest.raises(UserLocked) as exc:
        await use_case.execute(email="locked@x.io", mode="login")
    assert exc.value.code == "identity.user_locked"

    # No magic link, no email sent.
    assert len(links._by_id) == 0
    assert len(emails.sent) == 0


@pytest.mark.asyncio
async def test_ac_04_login_unknown_email_returns_success_no_email() -> None:
    use_case, _uow, users, links, emails, _gen = _wire()

    # Empty users repo; mode=login and email doesn't exist.
    result = await use_case.execute(email="ghost@x.io", mode="login")

    # Same response shape as success — prevents enumeration.
    assert isinstance(result, RequestMagicLinkResult)
    assert result.accepted is True

    # No new user created, no link, no email sent.
    assert len(users._by_id) == 0
    assert len(links._by_id) == 0
    assert len(emails.sent) == 0


@pytest.mark.asyncio
async def test_ac_01_idempotent_resend_creates_distinct_links() -> None:
    """Calling twice creates TWO distinct rows; both stay valid until consumed/expired."""
    use_case, _uow, _users, links, emails, _gen = _wire()

    await use_case.execute(email="x@y.io", mode="signup")
    await use_case.execute(email="x@y.io", mode="signup")

    assert len(links._by_id) == 2
    assert len(emails.sent) == 2


@pytest.mark.asyncio
async def test_ac_02_signup_for_existing_unverified_user_does_not_create_duplicate() -> None:
    """If a user already exists (unverified) and signs up again, no new user row.

    The use case is "request" not "create"; an unverified user re-doing
    signup is a 'resend' equivalent — fresh magic link, same user row.
    """
    use_case, _uow, users, links, _emails, _gen = _wire()
    e = Email("again@x.io")
    user = User.signup(email=e.value, email_hash=e.hash_blake2b())
    users.seed(user)
    pre_count = len(users._by_id)

    await use_case.execute(email="again@x.io", mode="signup")

    assert len(users._by_id) == pre_count
    link = next(iter(links._by_id.values()))
    assert link.user_id == user.id
