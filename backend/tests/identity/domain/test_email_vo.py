"""Email VO tests — AC-phase1-identity-001-08 (normalisation)."""

from __future__ import annotations

import pytest

from vaultchain.identity.domain.value_objects import Email
from vaultchain.shared.domain.errors import ValidationError


class TestEmailNormalization:
    def test_ac_08_lowercase_and_trim(self) -> None:
        assert Email("  USER@example.com ").value == "user@example.com"
        assert Email("Foo.Bar@Example.COM").value == "foo.bar@example.com"

    def test_normalisation_idempotent(self) -> None:
        once = Email("User@Example.com")
        twice = Email(once.value)
        assert once.value == twice.value


class TestEmailValidation:
    def test_rejects_empty_string(self) -> None:
        with pytest.raises(ValidationError):
            Email("")

    def test_rejects_whitespace_only(self) -> None:
        with pytest.raises(ValidationError):
            Email("   ")

    def test_rejects_no_at_sign(self) -> None:
        with pytest.raises(ValidationError):
            Email("not-an-email")

    def test_rejects_no_tld(self) -> None:
        with pytest.raises(ValidationError):
            Email("user@localhost")

    def test_rejects_too_long_total(self) -> None:
        long_local = "a" * 60
        long_domain = "x" * 200 + ".com"
        with pytest.raises(ValidationError):
            Email(f"{long_local}@{long_domain}")

    def test_rejects_too_long_local_part(self) -> None:
        with pytest.raises(ValidationError):
            Email("a" * 65 + "@example.com")

    def test_rejects_obviously_malformed(self) -> None:
        for bad in ["@example.com", "user@", "user@.com", "user@example.", "user @ example.com"]:
            with pytest.raises(ValidationError):
                Email(bad)


class TestEmailHash:
    def test_hash_is_deterministic_32_bytes(self) -> None:
        h1 = Email("user@example.com").hash_blake2b()
        h2 = Email("USER@example.com").hash_blake2b()
        assert h1 == h2
        assert len(h1) == 32

    def test_hash_differs_for_different_emails(self) -> None:
        a = Email("a@example.com").hash_blake2b()
        b = Email("b@example.com").hash_blake2b()
        assert a != b
