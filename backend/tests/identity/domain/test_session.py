"""Session aggregate tests — AC-phase1-identity-001-06."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from vaultchain.identity.domain.aggregates import Session


def _session(
    *,
    expires_at: datetime,
    revoked_at: datetime | None = None,
    version: int = 0,
) -> Session:
    now = datetime.now(UTC)
    return Session(
        id=uuid4(),
        user_id=uuid4(),
        refresh_token_hash=b"\x00" * 32,
        created_at=now,
        last_used_at=now,
        expires_at=expires_at,
        revoked_at=revoked_at,
        version=version,
    )


class TestIsActive:
    def test_ac_06_returns_true_when_not_expired_and_not_revoked(self) -> None:
        sess = _session(expires_at=datetime.now(UTC) + timedelta(days=1))
        assert sess.is_active() is True

    def test_ac_06_returns_false_when_expires_at_past(self) -> None:
        sess = _session(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        assert sess.is_active() is False

    def test_ac_06_returns_false_when_revoked_at_set(self) -> None:
        future = datetime.now(UTC) + timedelta(days=1)
        sess = _session(expires_at=future, revoked_at=datetime.now(UTC))
        assert sess.is_active() is False

    def test_ac_06_explicit_now_used_for_decision(self) -> None:
        anchor = datetime.now(UTC)
        sess = _session(expires_at=anchor + timedelta(seconds=10))
        assert sess.is_active(now=anchor) is True
        assert sess.is_active(now=anchor + timedelta(seconds=20)) is False


class TestRevoke:
    def test_ac_06_revoke_sets_revoked_at_and_bumps_version(self) -> None:
        sess = _session(
            expires_at=datetime.now(UTC) + timedelta(days=1),
            version=2,
        )
        sess.revoke()
        assert sess.revoked_at is not None
        assert sess.version == 3
        assert sess.is_active() is False

    def test_ac_06_revoke_is_idempotent_no_change_after_first_revoke(self) -> None:
        anchor = datetime.now(UTC)
        sess = _session(
            expires_at=anchor + timedelta(days=1),
            revoked_at=anchor - timedelta(seconds=10),
            version=5,
        )
        original_revoked = sess.revoked_at
        original_version = sess.version
        sess.revoke()  # no-op
        sess.revoke()  # no-op again
        assert sess.revoked_at == original_revoked
        assert sess.version == original_version

    def test_ac_06_revoke_with_explicit_now(self) -> None:
        anchor = datetime.now(UTC)
        sess = _session(expires_at=anchor + timedelta(days=1))
        sess.revoke(now=anchor)
        assert sess.revoked_at == anchor
