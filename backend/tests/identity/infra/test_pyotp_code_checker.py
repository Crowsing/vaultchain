"""PyOtpCodeChecker adapter tests — AC-phase1-identity-003-04, -10."""

from __future__ import annotations

import pyotp
import pytest

from vaultchain.identity.infra.totp.pyotp_checker import PyOtpCodeChecker


class TestVerifyWindow:
    def test_ac_04_accepts_current_window_code(self) -> None:
        checker = PyOtpCodeChecker()
        secret = checker.generate_secret()
        code = pyotp.TOTP(secret.decode("ascii")).now()
        assert checker.verify(secret, code) is True

    def test_ac_04_rejects_random_garbage(self) -> None:
        checker = PyOtpCodeChecker()
        secret = checker.generate_secret()
        # 6 zeros is statistically vanishingly unlikely for the current window.
        # If by 1-in-a-million chance it's accepted, retry once with a different
        # secret — but assert the typical case.
        if pyotp.TOTP(secret.decode("ascii")).now() == "000000":
            secret = checker.generate_secret()
        assert checker.verify(secret, "000000") is False

    def test_ac_04_accepts_one_window_in_the_past(self) -> None:
        """`valid_window=1` should tolerate -30s drift."""
        checker = PyOtpCodeChecker()
        secret = checker.generate_secret()
        totp = pyotp.TOTP(secret.decode("ascii"))
        # Compute the previous window's code via for_time.
        import time
        from datetime import UTC, datetime

        prev_code = totp.at(datetime.fromtimestamp(time.time() - 30, tz=UTC))
        assert checker.verify(secret, prev_code) is True


class TestQrPayloadUri:
    def test_ac_10_uri_starts_with_otpauth_totp_with_issuer(self) -> None:
        checker = PyOtpCodeChecker()
        secret = checker.generate_secret()
        uri = checker.qr_payload_uri(email="alice@example.com", secret=secret)
        # pyotp uses URL-encoding for the label; assert canonical components.
        assert uri.startswith("otpauth://totp/")
        assert "VaultChain" in uri
        assert "alice%40example.com" in uri or "alice@example.com" in uri
        assert f"secret={secret.decode('ascii')}" in uri
        assert "issuer=VaultChain" in uri


class TestSecretGeneration:
    def test_generate_secret_returns_base32_bytes(self) -> None:
        checker = PyOtpCodeChecker()
        s = checker.generate_secret()
        # base32 alphabet only (RFC 4648 standard).
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567=")
        assert isinstance(s, bytes)
        assert all(chr(b) in allowed for b in s)

    def test_each_call_yields_a_fresh_secret(self) -> None:
        checker = PyOtpCodeChecker()
        a = checker.generate_secret()
        b = checker.generate_secret()
        # Probability of collision is astronomical; if this fails, the RNG is broken.
        assert a != b


class TestProtocolConformance:
    def test_pyotp_checker_satisfies_totp_code_checker_protocol(self) -> None:
        from vaultchain.identity.domain.ports import TotpCodeChecker

        assert isinstance(PyOtpCodeChecker(), TotpCodeChecker)


# Ensure `pytest` is referenced at runtime so the import is not stripped if
# the test file shrinks; keeps tooling happy.
_ = pytest
