"""BcryptPasswordHasher adapter test — phase1-admin-002a Test Coverage."""

from __future__ import annotations

from vaultchain.identity.infra.bcrypt_password_hasher import BcryptPasswordHasher


def test_hash_format_starts_with_bcrypt_cost_marker() -> None:
    hasher = BcryptPasswordHasher(cost=4)  # cost 4 keeps the test fast
    digest = hasher.hash("a-strong-password-123")
    assert digest.startswith("$2b$04$")


def test_verify_roundtrip() -> None:
    hasher = BcryptPasswordHasher(cost=4)
    digest = hasher.hash("correct horse battery staple")
    assert hasher.verify("correct horse battery staple", digest) is True


def test_verify_rejects_wrong_password() -> None:
    hasher = BcryptPasswordHasher(cost=4)
    digest = hasher.hash("correct horse battery staple")
    assert hasher.verify("wrong-password", digest) is False


def test_verify_handles_malformed_hash() -> None:
    hasher = BcryptPasswordHasher(cost=4)
    assert hasher.verify("anything", "not-a-bcrypt-hash") is False
