"""PasswordHasher property tests — phase1-admin-002a Done Definition.

Driven against the in-memory fake; the `BcryptPasswordHasher` adapter
test in ``tests/identity/infra/`` exercises the same contract against
real bcrypt with a smaller sample to keep the suite fast.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.identity.fakes.fake_password_hasher import FakePasswordHasher
from vaultchain.identity.domain.value_objects import ADMIN_PASSWORD_MIN_LENGTH

_VALID_PASSWORDS = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126, blacklist_characters="$"),
    min_size=ADMIN_PASSWORD_MIN_LENGTH,
    max_size=64,
)


@settings(max_examples=50)
@given(password=_VALID_PASSWORDS)
def test_hash_verify_roundtrip(password: str) -> None:
    hasher = FakePasswordHasher()
    assert hasher.verify(password, hasher.hash(password)) is True


@settings(max_examples=50)
@given(p1=_VALID_PASSWORDS, p2=_VALID_PASSWORDS)
def test_distinct_passwords_do_not_verify(p1: str, p2: str) -> None:
    if p1 == p2:
        return
    hasher = FakePasswordHasher()
    assert hasher.verify(p1, hasher.hash(p2)) is False


def test_malformed_hash_rejected() -> None:
    hasher = FakePasswordHasher()
    assert hasher.verify("anything", "not-a-fake-hash") is False
