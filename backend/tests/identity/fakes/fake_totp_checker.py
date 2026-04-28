"""Deterministic `TotpCodeChecker` fake — no `pyotp` dependency.

Consumers seed a single fixed secret + a list of accepted codes; verify
returns True iff the code is in that list. The QR URI mirrors the
canonical `otpauth://` shape so tests can assert format.
"""

from __future__ import annotations


class FakeTotpCodeChecker:
    SECRET = b"FAKEFAKEFAKEFAKE"

    def __init__(self, *, accepted_codes: tuple[str, ...] = ()) -> None:
        self._accepted = set(accepted_codes)

    def generate_secret(self) -> bytes:
        return self.SECRET

    def verify(self, secret: bytes, code: str) -> bool:
        return code in self._accepted

    def qr_payload_uri(self, *, email: str, secret: bytes) -> str:
        return (
            f"otpauth://totp/VaultChain:{email}?"
            f"secret={secret.decode('ascii')}&issuer=VaultChain"
        )
