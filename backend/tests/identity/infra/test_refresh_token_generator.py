"""SecretsRefreshTokenGenerator adapter tests."""

from __future__ import annotations

from vaultchain.identity.domain.ports import RefreshTokenGenerator
from vaultchain.identity.infra.tokens.generator import (
    ACCESS_TOKEN_PREFIX,
    CSRF_TOKEN_PREFIX,
    REFRESH_TOKEN_PREFIX,
    SecretsRefreshTokenGenerator,
)


class TestPrefixesAndUniqueness:
    def test_access_token_uses_at_prefix(self) -> None:
        token = SecretsRefreshTokenGenerator().generate_access_token()
        assert token.startswith(ACCESS_TOKEN_PREFIX)

    def test_refresh_token_uses_rt_prefix(self) -> None:
        token = SecretsRefreshTokenGenerator().generate_refresh_token()
        assert token.startswith(REFRESH_TOKEN_PREFIX)

    def test_csrf_token_uses_csrf_prefix(self) -> None:
        token = SecretsRefreshTokenGenerator().generate_csrf_token()
        assert token.startswith(CSRF_TOKEN_PREFIX)

    def test_each_call_produces_a_unique_token(self) -> None:
        gen = SecretsRefreshTokenGenerator()
        a = gen.generate_access_token()
        b = gen.generate_access_token()
        assert a != b


class TestUrlSafe:
    def test_token_payload_is_url_safe(self) -> None:
        gen = SecretsRefreshTokenGenerator()
        token = gen.generate_refresh_token()
        # After stripping the prefix the body must be URL-safe-base64 alphabet.
        body = token[len(REFRESH_TOKEN_PREFIX) :]
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert all(c in allowed for c in body), body


class TestProtocolConformance:
    def test_generator_satisfies_refresh_token_generator_protocol(self) -> None:
        assert isinstance(SecretsRefreshTokenGenerator(), RefreshTokenGenerator)
