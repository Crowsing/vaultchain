"""Identity ports — repository Protocols + TOTP encryptor stub Protocol."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from vaultchain.identity.domain.aggregates import (
    MagicLink,
    Session,
    TotpSecret,
    User,
)


@dataclass(frozen=True)
class CachedAccessToken:
    """Value-object payload backed by Redis. ``scopes`` is the forward-compat
    hook for Phase-3 admin scopes; V1 user sessions get ``["user"]``.
    """

    user_id: UUID
    expires_at: datetime
    scopes: tuple[str, ...]
    session_id: UUID


@runtime_checkable
class UserRepository(Protocol):
    async def add(self, user: User) -> None: ...
    async def get_by_id(self, user_id: UUID) -> User | None: ...
    async def get_by_email(self, email_normalized: str) -> User | None: ...
    async def update(self, user: User) -> None: ...


@runtime_checkable
class SessionRepository(Protocol):
    async def add(self, session: Session) -> None: ...
    async def get_by_id(self, session_id: UUID) -> Session | None: ...
    async def get_by_refresh_token_hash(self, token_hash: bytes) -> Session | None: ...
    async def list_active_by_user_id(self, user_id: UUID) -> list[Session]: ...
    async def update(self, session: Session) -> None: ...


@runtime_checkable
class MagicLinkRepository(Protocol):
    async def add(self, link: MagicLink) -> None: ...
    async def get_by_token_hash(self, token_hash: bytes) -> MagicLink | None: ...
    async def update(self, link: MagicLink) -> None: ...


@runtime_checkable
class TotpSecretRepository(Protocol):
    async def add(self, secret: TotpSecret) -> None: ...
    async def get_by_user_id(self, user_id: UUID) -> TotpSecret | None: ...
    async def update(self, secret: TotpSecret) -> None: ...


@runtime_checkable
class TotpSecretEncryptor(Protocol):
    """Encrypt / decrypt a TOTP secret. V1 stub uses a static config key;
    the KMS brief (Phase 2) replaces with per-secret data keys."""

    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...


@runtime_checkable
class TotpCodeChecker(Protocol):
    """Generates TOTP secrets, verifies user-provided codes, and renders
    the otpauth URI consumed by authenticator apps. Production adapter
    wraps `pyotp`; tests inject a deterministic fake.
    """

    def generate_secret(self) -> bytes: ...
    def verify(self, secret: bytes, code: str) -> bool: ...
    def qr_payload_uri(self, *, email: str, secret: bytes) -> str: ...


@runtime_checkable
class AccessTokenCache(Protocol):
    """Cache the access-token payload by ``sha256(token)`` hex digest.

    Implemented in V1 by Redis with ``SET EX`` for TTL. ``evict_by_session``
    is the seam revocation uses to invalidate the *current* access-token
    cache entry without the route handler holding the raw token (the route
    only knows the session id).
    """

    async def set(self, token_sha256_hex: str, payload: CachedAccessToken) -> None: ...
    async def get(self, token_sha256_hex: str) -> CachedAccessToken | None: ...
    async def evict(self, token_sha256_hex: str) -> None: ...
    async def evict_by_session(self, session_id: UUID) -> None: ...


@runtime_checkable
class RefreshTokenGenerator(Protocol):
    """Pluggable token issuance — production uses ``secrets.token_urlsafe``,
    tests inject a deterministic seed for reproducibility.
    """

    def generate_access_token(self) -> str: ...
    def generate_refresh_token(self) -> str: ...
    def generate_csrf_token(self) -> str: ...


@runtime_checkable
class BackupCodeService(Protocol):
    """Generates and validates one-time backup codes.

    The plaintext is shown to the user exactly once at enrollment (or
    regeneration); only argon2id hashes are persisted. The service
    finds a matching hash so the use case can remove it from the
    user's stored list (one-time use, AC-phase1-identity-003-08).
    """

    def generate(self, count: int = 10) -> list[str]: ...
    def hash(self, code: str) -> bytes: ...
    def find_matching_hash(self, code: str, hashes: list[bytes]) -> bytes | None: ...


__all__ = [
    "AccessTokenCache",
    "BackupCodeService",
    "CachedAccessToken",
    "MagicLinkRepository",
    "RefreshTokenGenerator",
    "SessionRepository",
    "TotpCodeChecker",
    "TotpSecretEncryptor",
    "TotpSecretRepository",
    "UserRepository",
]
