"""In-memory `UserRepository`, `TotpSecretRepository`, and `SessionRepository` fakes.

Tests instantiate one repo per test, populate it with seed data, and
inject it via a factory that ignores the session (the factory shape
matches what production wiring expects).
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from uuid import UUID

from vaultchain.identity.domain.aggregates import (
    Session,
    TotpSecret,
    User,
)
from vaultchain.shared.domain.errors import StaleAggregate


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._by_id: dict[UUID, User] = {}

    def seed(self, user: User) -> None:
        self._by_id[user.id] = copy.deepcopy(user)

    async def add(self, user: User) -> None:
        self._by_id[user.id] = copy.deepcopy(user)

    async def get_by_id(self, user_id: UUID) -> User | None:
        u = self._by_id.get(user_id)
        return copy.deepcopy(u) if u else None

    async def get_by_email(self, email_normalized: str) -> User | None:
        for u in self._by_id.values():
            if u.email == email_normalized.strip().lower():
                return copy.deepcopy(u)
        return None

    async def update(self, user: User) -> None:
        existing = self._by_id.get(user.id)
        if existing is None:
            raise StaleAggregate(details={"aggregate_id": str(user.id), "kind": "user"})
        if existing.version != user.version - 1:
            raise StaleAggregate(details={"aggregate_id": str(user.id), "kind": "user"})
        self._by_id[user.id] = copy.deepcopy(user)


class InMemoryTotpSecretRepository:
    def __init__(self) -> None:
        self._by_user: dict[UUID, TotpSecret] = {}

    def seed(self, secret: TotpSecret) -> None:
        self._by_user[secret.user_id] = copy.deepcopy(secret)

    async def add(self, secret: TotpSecret) -> None:
        self._by_user[secret.user_id] = copy.deepcopy(secret)

    async def get_by_user_id(self, user_id: UUID) -> TotpSecret | None:
        s = self._by_user.get(user_id)
        return copy.deepcopy(s) if s else None

    async def update(self, secret: TotpSecret) -> None:
        if secret.user_id not in self._by_user:
            raise StaleAggregate(details={"aggregate_id": str(secret.id), "kind": "totp_secret"})
        self._by_user[secret.user_id] = copy.deepcopy(secret)


class InMemorySessionRepository:
    def __init__(self) -> None:
        self._by_id: dict[UUID, Session] = {}

    def seed(self, session: Session) -> None:
        self._by_id[session.id] = copy.deepcopy(session)

    async def add(self, session: Session) -> None:
        self._by_id[session.id] = copy.deepcopy(session)

    async def get_by_id(self, session_id: UUID) -> Session | None:
        s = self._by_id.get(session_id)
        return copy.deepcopy(s) if s else None

    async def get_by_refresh_token_hash(self, token_hash: bytes) -> Session | None:
        for s in self._by_id.values():
            if s.refresh_token_hash == token_hash:
                return copy.deepcopy(s)
        return None

    async def list_active_by_user_id(self, user_id: UUID) -> list[Session]:
        now = datetime.now(UTC)
        return [
            copy.deepcopy(s)
            for s in self._by_id.values()
            if s.user_id == user_id and s.revoked_at is None and s.expires_at > now
        ]

    async def update(self, sess: Session) -> None:
        existing = self._by_id.get(sess.id)
        if existing is None:
            raise StaleAggregate(details={"aggregate_id": str(sess.id), "kind": "session"})
        if existing.version != sess.version - 1:
            raise StaleAggregate(details={"aggregate_id": str(sess.id), "kind": "session"})
        self._by_id[sess.id] = copy.deepcopy(sess)
