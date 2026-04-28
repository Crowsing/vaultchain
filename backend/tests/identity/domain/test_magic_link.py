"""MagicLink aggregate tests — AC-phase1-identity-001-05."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from vaultchain.identity.domain.aggregates import MagicLink
from vaultchain.identity.domain.errors import (
    MagicLinkAlreadyUsed,
    MagicLinkExpired,
)


def _link(
    *,
    expires_at: datetime,
    consumed_at: datetime | None = None,
    mode: str = "login",
) -> MagicLink:
    now = datetime.now(UTC)
    return MagicLink(
        id=uuid4(),
        user_id=uuid4(),
        token_hash=b"\xde\xad\xbe\xef" * 8,
        mode=mode,  # type: ignore[arg-type]
        created_at=now,
        expires_at=expires_at,
        consumed_at=consumed_at,
    )


class TestConsume:
    def test_consume_sets_consumed_at(self) -> None:
        link = _link(expires_at=datetime.now(UTC) + timedelta(minutes=15))
        link.consume()
        assert link.consumed_at is not None

    def test_consume_with_explicit_now(self) -> None:
        anchor = datetime.now(UTC)
        link = _link(expires_at=anchor + timedelta(minutes=15))
        link.consume(now=anchor)
        assert link.consumed_at == anchor

    def test_ac_05_expired_link_raises_magic_link_expired(self) -> None:
        link = _link(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        with pytest.raises(MagicLinkExpired) as exc:
            link.consume()
        assert exc.value.code == "identity.magic_link_expired"
        assert "magic_link_id" in exc.value.details

    def test_ac_05_already_consumed_link_raises_magic_link_already_used(self) -> None:
        anchor = datetime.now(UTC)
        link = _link(
            expires_at=anchor + timedelta(minutes=15),
            consumed_at=anchor - timedelta(seconds=1),
        )
        with pytest.raises(MagicLinkAlreadyUsed) as exc:
            link.consume()
        assert exc.value.code == "identity.magic_link_already_used"

    def test_ac_05_already_consumed_takes_precedence_over_expired(self) -> None:
        """If both conditions hold, AlreadyUsed reads more diagnostically."""
        anchor = datetime.now(UTC)
        link = _link(
            expires_at=anchor - timedelta(minutes=10),
            consumed_at=anchor - timedelta(minutes=5),
        )
        with pytest.raises(MagicLinkAlreadyUsed):
            link.consume()
