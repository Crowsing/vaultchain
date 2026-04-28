"""SecretsMagicLinkTokenGenerator adapter tests."""

from __future__ import annotations

from vaultchain.identity.infra.tokens.magic_link_generator import (
    SecretsMagicLinkTokenGenerator,
)


def test_token_generator_produces_urlsafe_string() -> None:
    gen = SecretsMagicLinkTokenGenerator()
    tok = gen.generate()
    assert isinstance(tok, str)
    # urlsafe alphabet: letters, digits, hyphen, underscore. No padding.
    assert all(ch.isalnum() or ch in "-_" for ch in tok), tok
    assert "=" not in tok
    # 32 random bytes ⇒ 43 base64-urlsafe chars (no padding).
    assert len(tok) >= 32


def test_token_generator_is_random() -> None:
    """Two calls produce different tokens — would be 1 in 2**256 to collide."""
    gen = SecretsMagicLinkTokenGenerator()
    a = gen.generate()
    b = gen.generate()
    assert a != b
