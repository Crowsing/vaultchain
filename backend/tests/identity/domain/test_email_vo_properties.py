"""Hypothesis property tests for `Email` normalisation — AC-phase1-identity-001-08."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from vaultchain.identity.domain.value_objects import Email

pytestmark = pytest.mark.property

# Locals: 1..60 chars from a conservative RFC-5321 alnum/dot/underscore set.
# Domains: alnum host with a 2..6 letter TLD. We sample only well-formed shapes
# because the property under test is normalisation-roundtrip, not parser
# fuzzing. Validation rejection is covered in `test_email_vo.py`.

_LOCAL_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._"
_HOST_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

_local = st.text(alphabet=_LOCAL_ALPHABET, min_size=1, max_size=30).filter(
    lambda s: not s.startswith(".") and not s.endswith(".") and ".." not in s
)
_host = st.text(alphabet=_HOST_ALPHABET, min_size=1, max_size=30).filter(
    lambda s: not s.startswith("-") and not s.endswith("-")
)
_tld = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
    min_size=2,
    max_size=6,
)
_emails = st.tuples(_local, _host, _tld).map(lambda t: f"{t[0]}@{t[1]}.{t[2]}")


@given(_emails)
def test_normalisation_idempotent_under_case_change(email: str) -> None:
    a = Email(email).value
    b = Email(email.upper()).value
    c = Email(email.lower()).value
    assert a == b == c


@given(_emails)
def test_normalisation_idempotent_under_whitespace_padding(email: str) -> None:
    a = Email(email).value
    b = Email(f"  {email}  ").value
    c = Email(f"\t{email}\n").value
    assert a == b == c


@given(_emails)
def test_double_construction_is_stable(email: str) -> None:
    once = Email(email).value
    twice = Email(once).value
    assert once == twice
