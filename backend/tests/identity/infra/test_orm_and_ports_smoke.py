"""ORM mapping + Protocol conformance smoke tests.

Imports `identity.infra.orm` so SQLAlchemy registers the table mappings on
``Base.metadata`` and verifies the SQLAlchemy repositories conform to the
identity ports (covers AC-09's optimistic-lock plumbing surface).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from vaultchain.identity.domain.ports import (
    MagicLinkRepository,
    SessionRepository,
    TotpSecretEncryptor,
    TotpSecretRepository,
    UserRepository,
)
from vaultchain.identity.infra.orm import (
    MagicLinkRow,
    SessionRow,
    TotpSecretRow,
    UserRow,
)
from vaultchain.identity.infra.repositories import (
    SqlAlchemyMagicLinkRepository,
    SqlAlchemySessionRepository,
    SqlAlchemyTotpSecretRepository,
    SqlAlchemyUserRepository,
)
from vaultchain.identity.infra.totp_encryptor import StaticKeyTotpEncryptor


class TestOrmMetadata:
    def test_users_row_lives_in_identity_schema(self) -> None:
        assert UserRow.__tablename__ == "users"
        assert UserRow.__table__.schema == "identity"
        assert "email" in UserRow.__table__.columns
        assert "version" in UserRow.__table__.columns

    def test_sessions_row_has_fk_to_users(self) -> None:
        assert SessionRow.__tablename__ == "sessions"
        assert SessionRow.__table__.schema == "identity"
        fk_targets = {fk.target_fullname for fk in SessionRow.__table__.foreign_keys}
        assert "identity.users.id" in fk_targets

    def test_magic_links_row_has_mode_check_constraint(self) -> None:
        from sqlalchemy import CheckConstraint

        assert MagicLinkRow.__tablename__ == "magic_links"
        check_clauses = [
            str(c.sqltext)
            for c in MagicLinkRow.__table__.constraints
            if isinstance(c, CheckConstraint)
        ]
        assert any("mode" in clause and "signup" in clause for clause in check_clauses)

    def test_totp_secrets_row_has_unique_user_id(self) -> None:
        assert TotpSecretRow.__tablename__ == "totp_secrets"
        user_id_col = TotpSecretRow.__table__.columns["user_id"]
        assert user_id_col.unique is True


class TestPortConformance:
    def test_user_repo_satisfies_user_repository_protocol(self) -> None:
        adapter = SqlAlchemyUserRepository(MagicMock())
        assert isinstance(adapter, UserRepository)

    def test_session_repo_satisfies_session_repository_protocol(self) -> None:
        adapter = SqlAlchemySessionRepository(MagicMock())
        assert isinstance(adapter, SessionRepository)

    def test_magic_link_repo_satisfies_magic_link_repository_protocol(self) -> None:
        adapter = SqlAlchemyMagicLinkRepository(MagicMock())
        assert isinstance(adapter, MagicLinkRepository)

    def test_totp_secret_repo_satisfies_totp_secret_repository_protocol(self) -> None:
        adapter = SqlAlchemyTotpSecretRepository(MagicMock())
        assert isinstance(adapter, TotpSecretRepository)

    def test_static_key_encryptor_satisfies_totp_secret_encryptor_protocol(self) -> None:
        enc = StaticKeyTotpEncryptor.from_passphrase("p")
        assert isinstance(enc, TotpSecretEncryptor)
