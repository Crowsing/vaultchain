"""StaticKeyTotpEncryptor unit tests — V1 placeholder, AC-phase1-identity-001-07."""

from __future__ import annotations

import pytest

from vaultchain.identity.infra.totp_encryptor import StaticKeyTotpEncryptor


class TestEncryptDecryptRoundTrip:
    def test_round_trip_yields_original_plaintext(self) -> None:
        enc = StaticKeyTotpEncryptor.from_passphrase("a passphrase")
        plain = b"otpsecret-32-bytes-fixed-content"
        ciphertext = enc.encrypt(plain)
        assert ciphertext != plain
        assert enc.decrypt(ciphertext) == plain

    def test_each_encryption_uses_fresh_nonce(self) -> None:
        enc = StaticKeyTotpEncryptor.from_passphrase("p")
        a = enc.encrypt(b"x")
        b = enc.encrypt(b"x")
        assert a != b
        assert enc.decrypt(a) == enc.decrypt(b) == b"x"

    def test_empty_plaintext_round_trips(self) -> None:
        enc = StaticKeyTotpEncryptor.from_passphrase("p")
        assert enc.decrypt(enc.encrypt(b"")) == b""


class TestKeyHandling:
    def test_constructor_rejects_wrong_key_length(self) -> None:
        with pytest.raises(ValueError, match="32-byte key"):
            StaticKeyTotpEncryptor(b"too short")

    def test_from_passphrase_derives_32_byte_key(self) -> None:
        enc = StaticKeyTotpEncryptor.from_passphrase("any string")
        # If construction succeeds, the derived key was the right length.
        assert enc.encrypt(b"x") != b"x"

    def test_from_env_requires_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IDENTITY_TOTP_ENCRYPT_KEY", raising=False)
        with pytest.raises(RuntimeError, match="IDENTITY_TOTP_ENCRYPT_KEY"):
            StaticKeyTotpEncryptor.from_env()

    def test_from_env_reads_passphrase_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("IDENTITY_TOTP_ENCRYPT_KEY", "env-passphrase")
        enc = StaticKeyTotpEncryptor.from_env()
        assert enc.decrypt(enc.encrypt(b"y")) == b"y"


class TestCiphertextValidation:
    def test_decrypt_rejects_short_ciphertext(self) -> None:
        enc = StaticKeyTotpEncryptor.from_passphrase("p")
        with pytest.raises(ValueError, match="too short"):
            enc.decrypt(b"\x00" * 5)

    def test_decrypt_with_different_key_fails(self) -> None:
        from cryptography.exceptions import InvalidTag

        enc_a = StaticKeyTotpEncryptor.from_passphrase("a")
        enc_b = StaticKeyTotpEncryptor.from_passphrase("b")
        ct = enc_a.encrypt(b"secret")
        with pytest.raises(InvalidTag):
            enc_b.decrypt(ct)
