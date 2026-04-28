"""Argon2BackupCodeService adapter tests — AC-phase1-identity-003-08, -09."""

from __future__ import annotations

import re

import pytest
from argon2 import PasswordHasher

from vaultchain.identity.infra.totp.backup_codes import Argon2BackupCodeService

# Cheap test-only profile: argon2 default takes ~50ms which adds up across
# many tests. Bring it down to keep `pytest` runs snappy without weakening
# what's being verified (round-trip + miss).
_TEST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


class TestGenerate:
    def test_generate_returns_count_codes(self) -> None:
        svc = Argon2BackupCodeService(hasher=_TEST_HASHER)
        codes = svc.generate(10)
        assert len(codes) == 10

    def test_generate_codes_match_xxxx_xxxx_format(self) -> None:
        svc = Argon2BackupCodeService(hasher=_TEST_HASHER)
        for c in svc.generate(10):
            assert re.match(r"^[A-Z0-9]{4}-[A-Z0-9]{4}$", c), c

    def test_generate_excludes_visually_ambiguous_chars(self) -> None:
        svc = Argon2BackupCodeService(hasher=_TEST_HASHER)
        for c in svc.generate(20):
            for ch in c:
                if ch == "-":
                    continue
                assert ch not in "IO01"


class TestHashAndVerify:
    def test_argon2id_round_trip_finds_match(self) -> None:
        svc = Argon2BackupCodeService(hasher=_TEST_HASHER)
        codes = svc.generate(10)
        hashes = [svc.hash(c) for c in codes]
        target = codes[3]
        match = svc.find_matching_hash(target, hashes)
        assert match is not None
        assert match == hashes[3]

    def test_find_matching_hash_returns_none_on_miss(self) -> None:
        svc = Argon2BackupCodeService(hasher=_TEST_HASHER)
        codes = svc.generate(5)
        hashes = [svc.hash(c) for c in codes]
        assert svc.find_matching_hash("FAKE-CODE", hashes) is None

    def test_each_hash_is_unique_for_same_code(self) -> None:
        """argon2id uses a per-call salt — two hashes of the same plaintext differ."""
        svc = Argon2BackupCodeService(hasher=_TEST_HASHER)
        a = svc.hash("ABCD-EFGH")
        b = svc.hash("ABCD-EFGH")
        assert a != b
        # But both verify against the original.
        assert svc.find_matching_hash("ABCD-EFGH", [a, b]) is not None


class TestProtocolConformance:
    def test_argon2_service_satisfies_backup_code_service_protocol(self) -> None:
        from vaultchain.identity.domain.ports import BackupCodeService

        assert isinstance(Argon2BackupCodeService(hasher=_TEST_HASHER), BackupCodeService)


# Suppress unused-import lint if `pytest` is otherwise unused at runtime.
_ = pytest
