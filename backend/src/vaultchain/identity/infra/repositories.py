"""Concrete SQLAlchemy repositories for the identity aggregates.

Each repository wraps an `AsyncSession` provided by the UoW. `update()`
includes optimistic-lock plumbing: `UPDATE ... WHERE version=?` and raises
`StaleAggregate` if `rowcount == 0`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from vaultchain.identity.domain.aggregates import (
    MagicLink,
    Session,
    TotpSecret,
    User,
    UserStatus,
)
from vaultchain.shared.domain.errors import StaleAggregate


def _user_from_row(row: sa.Row[Any]) -> User:
    return User(
        id=row.id,
        email=row.email,
        email_hash=bytes(row.email_hash),
        status=UserStatus(row.status),
        kyc_tier=row.kyc_tier,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        failed_totp_attempts=row.failed_totp_attempts,
        locked_until=row.locked_until,
    )


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> None:
        await self._session.execute(
            sa.text(
                "INSERT INTO identity.users "
                "(id, email, email_hash, status, kyc_tier, version, created_at) "
                "VALUES (:id, :email, :email_hash, :status, :kyc_tier, :version, :created_at)"
            ),
            {
                "id": user.id,
                "email": user.email,
                "email_hash": user.email_hash,
                "status": user.status.value,
                "kyc_tier": user.kyc_tier,
                "version": user.version,
                "created_at": user.created_at,
            },
        )

    async def get_by_id(self, user_id: UUID) -> User | None:
        row = (
            await self._session.execute(
                sa.text("SELECT * FROM identity.users WHERE id=:id"),
                {"id": user_id},
            )
        ).one_or_none()
        return _user_from_row(row) if row else None

    async def get_by_email(self, email_normalized: str) -> User | None:
        row = (
            await self._session.execute(
                sa.text("SELECT * FROM identity.users WHERE email=:email"),
                {"email": email_normalized.strip().lower()},
            )
        ).one_or_none()
        return _user_from_row(row) if row else None

    async def update(self, user: User) -> None:
        result = await self._session.execute(
            sa.text(
                "UPDATE identity.users "
                "SET status=:status, kyc_tier=:kyc_tier, "
                "failed_totp_attempts=:fail_count, locked_until=:locked_until, "
                "version=version+1, updated_at=NOW() "
                "WHERE id=:id AND version=:expected_version"
            ),
            {
                "id": user.id,
                "status": user.status.value,
                "kyc_tier": user.kyc_tier,
                "fail_count": user.failed_totp_attempts,
                "locked_until": user.locked_until,
                "expected_version": user.version - 1,  # caller bumped it on the entity
            },
        )
        if getattr(result, "rowcount", 0) == 0:
            raise StaleAggregate(details={"aggregate_id": str(user.id), "kind": "user"})


class SqlAlchemySessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, sess: Session) -> None:
        await self._session.execute(
            sa.text(
                "INSERT INTO identity.sessions "
                "(id, user_id, refresh_token_hash, created_at, last_used_at, expires_at, "
                "revoked_at, user_agent, ip_inet, version) "
                "VALUES (:id, :user_id, :token, :created_at, :last_used_at, :expires_at, "
                ":revoked_at, :user_agent, :ip_inet, :version)"
            ),
            {
                "id": sess.id,
                "user_id": sess.user_id,
                "token": sess.refresh_token_hash,
                "created_at": sess.created_at,
                "last_used_at": sess.last_used_at,
                "expires_at": sess.expires_at,
                "revoked_at": sess.revoked_at,
                "user_agent": sess.user_agent,
                "ip_inet": sess.ip_inet,
                "version": sess.version,
            },
        )

    async def get_by_id(self, session_id: UUID) -> Session | None:
        row = (
            await self._session.execute(
                sa.text("SELECT * FROM identity.sessions WHERE id=:id"),
                {"id": session_id},
            )
        ).one_or_none()
        return _session_from_row(row) if row else None

    async def get_by_refresh_token_hash(self, token_hash: bytes) -> Session | None:
        row = (
            await self._session.execute(
                sa.text("SELECT * FROM identity.sessions WHERE refresh_token_hash=:t"),
                {"t": token_hash},
            )
        ).one_or_none()
        return _session_from_row(row) if row else None

    async def list_active_by_user_id(self, user_id: UUID) -> list[Session]:
        rows = (
            await self._session.execute(
                sa.text(
                    "SELECT * FROM identity.sessions "
                    "WHERE user_id=:uid AND revoked_at IS NULL AND expires_at > NOW()"
                ),
                {"uid": user_id},
            )
        ).all()
        return [_session_from_row(r) for r in rows]

    async def update(self, sess: Session) -> None:
        result = await self._session.execute(
            sa.text(
                "UPDATE identity.sessions "
                "SET last_used_at=:last_used_at, revoked_at=:revoked_at, "
                "version=version+1 "
                "WHERE id=:id AND version=:expected"
            ),
            {
                "id": sess.id,
                "last_used_at": sess.last_used_at,
                "revoked_at": sess.revoked_at,
                "expected": sess.version - 1,
            },
        )
        if getattr(result, "rowcount", 0) == 0:
            raise StaleAggregate(details={"aggregate_id": str(sess.id), "kind": "session"})


def _session_from_row(row: sa.Row[Any]) -> Session:
    return Session(
        id=row.id,
        user_id=row.user_id,
        refresh_token_hash=bytes(row.refresh_token_hash),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        user_agent=row.user_agent,
        ip_inet=row.ip_inet,
        version=row.version,
    )


class SqlAlchemyMagicLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, link: MagicLink) -> None:
        await self._session.execute(
            sa.text(
                "INSERT INTO identity.magic_links "
                "(id, user_id, token_hash, mode, created_at, expires_at, consumed_at) "
                "VALUES (:id, :user_id, :token, :mode, :created_at, :expires_at, :consumed_at)"
            ),
            {
                "id": link.id,
                "user_id": link.user_id,
                "token": link.token_hash,
                "mode": link.mode,
                "created_at": link.created_at,
                "expires_at": link.expires_at,
                "consumed_at": link.consumed_at,
            },
        )

    async def get_by_token_hash(self, token_hash: bytes) -> MagicLink | None:
        row = (
            await self._session.execute(
                sa.text("SELECT * FROM identity.magic_links WHERE token_hash=:t"),
                {"t": token_hash},
            )
        ).one_or_none()
        if not row:
            return None
        return MagicLink(
            id=row.id,
            user_id=row.user_id,
            token_hash=bytes(row.token_hash),
            mode=row.mode,
            created_at=row.created_at,
            expires_at=row.expires_at,
            consumed_at=row.consumed_at,
        )

    async def update(self, link: MagicLink) -> None:
        await self._session.execute(
            sa.text("UPDATE identity.magic_links SET consumed_at=:consumed_at WHERE id=:id"),
            {"id": link.id, "consumed_at": link.consumed_at},
        )


class SqlAlchemyTotpSecretRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, secret: TotpSecret) -> None:
        await self._session.execute(
            sa.text(
                "INSERT INTO identity.totp_secrets "
                "(id, user_id, secret_encrypted, backup_codes_hashed, "
                "enrolled_at, last_verified_at) "
                "VALUES (:id, :user_id, :secret, :codes, :enrolled_at, :last_verified_at)"
            ),
            {
                "id": secret.id,
                "user_id": secret.user_id,
                "secret": secret.secret_encrypted,
                "codes": secret.backup_codes_hashed,
                "enrolled_at": secret.enrolled_at,
                "last_verified_at": secret.last_verified_at,
            },
        )

    async def get_by_user_id(self, user_id: UUID) -> TotpSecret | None:
        row = (
            await self._session.execute(
                sa.text("SELECT * FROM identity.totp_secrets WHERE user_id=:id"),
                {"id": user_id},
            )
        ).one_or_none()
        if not row:
            return None
        return TotpSecret(
            id=row.id,
            user_id=row.user_id,
            secret_encrypted=bytes(row.secret_encrypted),
            backup_codes_hashed=[bytes(c) for c in (row.backup_codes_hashed or [])],
            enrolled_at=row.enrolled_at,
            last_verified_at=row.last_verified_at,
        )

    async def update(self, secret: TotpSecret) -> None:
        await self._session.execute(
            sa.text(
                "UPDATE identity.totp_secrets "
                "SET secret_encrypted=:secret, backup_codes_hashed=:codes, "
                "last_verified_at=:last_verified_at "
                "WHERE id=:id"
            ),
            {
                "id": secret.id,
                "secret": secret.secret_encrypted,
                "codes": secret.backup_codes_hashed,
                "last_verified_at": secret.last_verified_at,
            },
        )


__all__ = [
    "SqlAlchemyMagicLinkRepository",
    "SqlAlchemySessionRepository",
    "SqlAlchemyTotpSecretRepository",
    "SqlAlchemyUserRepository",
]
