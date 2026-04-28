"""In-memory `PreTotpTokenCache` fake."""

from __future__ import annotations

from vaultchain.identity.domain.ports import PreTotpPayload


class FakePreTotpTokenCache:
    def __init__(self) -> None:
        self._store: dict[str, PreTotpPayload] = {}

    async def set(self, token_sha256_hex: str, payload: PreTotpPayload) -> None:
        self._store[token_sha256_hex] = payload

    async def get(self, token_sha256_hex: str) -> PreTotpPayload | None:
        return self._store.get(token_sha256_hex)

    async def evict(self, token_sha256_hex: str) -> None:
        self._store.pop(token_sha256_hex, None)


__all__ = ["FakePreTotpTokenCache"]
