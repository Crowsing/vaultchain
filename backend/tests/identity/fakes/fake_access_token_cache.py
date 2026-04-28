"""In-memory `AccessTokenCache` fake — dict-backed, no Redis."""

from __future__ import annotations

from uuid import UUID

from vaultchain.identity.domain.ports import CachedAccessToken


class FakeAccessTokenCache:
    def __init__(self) -> None:
        self._store: dict[str, CachedAccessToken] = {}
        self._session_index: dict[UUID, str] = {}

    async def set(self, token_sha256_hex: str, payload: CachedAccessToken) -> None:
        self._store[token_sha256_hex] = payload
        self._session_index[payload.session_id] = token_sha256_hex

    async def get(self, token_sha256_hex: str) -> CachedAccessToken | None:
        return self._store.get(token_sha256_hex)

    async def evict(self, token_sha256_hex: str) -> None:
        payload = self._store.pop(token_sha256_hex, None)
        if payload is not None:
            self._session_index.pop(payload.session_id, None)

    async def evict_by_session(self, session_id: UUID) -> None:
        token_hex = self._session_index.pop(session_id, None)
        if token_hex is not None:
            self._store.pop(token_hex, None)
