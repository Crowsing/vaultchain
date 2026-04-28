"""In-memory `FakeTotpEncryptor` for unit-level tests of `TotpSecret.enroll`."""

from __future__ import annotations


class FakeTotpEncryptor:
    """Reversible identity wrapper: ``decrypt(encrypt(x)) == x``.

    Prepends a 1-byte sentinel so plaintext != ciphertext, which is enough
    to validate the port contract without depending on real cryptography.
    """

    SENTINEL = b"\x01"

    def encrypt(self, plaintext: bytes) -> bytes:
        return self.SENTINEL + plaintext

    def decrypt(self, ciphertext: bytes) -> bytes:
        if not ciphertext.startswith(self.SENTINEL):
            raise ValueError("FakeTotpEncryptor: missing sentinel")
        return ciphertext[len(self.SENTINEL) :]
