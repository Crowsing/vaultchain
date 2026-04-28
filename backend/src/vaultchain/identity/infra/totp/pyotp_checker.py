"""`pyotp`-backed `TotpCodeChecker` adapter.

Production wiring uses ``pyotp.TOTP(secret).verify(code, valid_window=1)``
so a 30-second window plus ±30s clock-drift tolerance is honoured (the
brief mandates 90-second total tolerance to handle device drift).
"""

from __future__ import annotations

import pyotp


class PyOtpCodeChecker:
    """Adapter on top of `pyotp` exposed as ``TotpCodeChecker``."""

    #: TOTP step (seconds). Inherits pyotp default; pinned for clarity.
    INTERVAL: int = 30
    #: Number of windows on each side accepted; 1 → 90s total window.
    VALID_WINDOW: int = 1

    @staticmethod
    def generate_secret() -> bytes:
        """Generate a base32-encoded TOTP secret (returned as bytes for the port)."""
        return pyotp.random_base32().encode("ascii")

    def verify(self, secret: bytes, code: str) -> bool:
        return bool(
            pyotp.TOTP(secret.decode("ascii"), interval=self.INTERVAL).verify(
                code, valid_window=self.VALID_WINDOW
            )
        )

    def qr_payload_uri(self, *, email: str, secret: bytes) -> str:
        """`otpauth://` URI per AC-phase1-identity-003-10."""
        return pyotp.TOTP(secret.decode("ascii"), interval=self.INTERVAL).provisioning_uri(
            name=email, issuer_name="VaultChain"
        )


__all__ = ["PyOtpCodeChecker"]
