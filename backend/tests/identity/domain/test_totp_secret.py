"""TotpSecret aggregate tests — AC-phase1-identity-001-07 (encryptor port contract)."""

from __future__ import annotations

from uuid import uuid4

from tests.identity.fakes.fake_encryptor import FakeTotpEncryptor
from vaultchain.identity.domain.aggregates import TotpSecret


class TestEnroll:
    def test_ac_07_enroll_encrypts_secret_via_port(self) -> None:
        encryptor = FakeTotpEncryptor()
        plain = b"otp-seed-32-bytes-aaaaaaaaaaaaaa"
        ts = TotpSecret.enroll(
            user_id=uuid4(),
            secret_plain=plain,
            backup_codes_hashed=[b"hash-1", b"hash-2"],
            encryptor=encryptor,
        )
        assert ts.secret_encrypted != plain
        assert ts.secret_encrypted.startswith(FakeTotpEncryptor.SENTINEL)

    def test_ac_07_decrypt_round_trip_yields_original_plaintext(self) -> None:
        encryptor = FakeTotpEncryptor()
        plain = b"another-seed"
        ts = TotpSecret.enroll(
            user_id=uuid4(),
            secret_plain=plain,
            backup_codes_hashed=[],
            encryptor=encryptor,
        )
        assert ts.decrypt(encryptor) == plain

    def test_enroll_persists_backup_codes_as_a_copy(self) -> None:
        encryptor = FakeTotpEncryptor()
        codes = [b"code-1", b"code-2"]
        ts = TotpSecret.enroll(
            user_id=uuid4(),
            secret_plain=b"x",
            backup_codes_hashed=codes,
            encryptor=encryptor,
        )
        codes.append(b"code-3")
        assert ts.backup_codes_hashed == [b"code-1", b"code-2"]

    def test_enroll_assigns_id_and_user_id_and_enrolled_at(self) -> None:
        encryptor = FakeTotpEncryptor()
        user_id = uuid4()
        ts = TotpSecret.enroll(
            user_id=user_id,
            secret_plain=b"x",
            backup_codes_hashed=[],
            encryptor=encryptor,
        )
        assert ts.user_id == user_id
        assert ts.last_verified_at is None
        assert ts.id is not None
        assert ts.enrolled_at is not None
