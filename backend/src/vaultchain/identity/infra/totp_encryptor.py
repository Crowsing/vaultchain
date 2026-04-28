"""Static-key TOTP secret encryptor — V1 placeholder.

Encrypts the raw TOTP secret with AES-GCM using a key derived from the
`IDENTITY_TOTP_ENCRYPT_KEY` settings env var. **Single static key for all
secrets.** The KMS brief replaces this with per-secret data keys.

# TODO(phase2-custody-kms-001): replace with real KMS envelope encryption.
"""

from __future__ import annotations

import os
from hashlib import sha256

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_LEN = 32
_NONCE_LEN = 12


class StaticKeyTotpEncryptor:
    """AES-GCM with a single 256-bit key derived from a settings env var.

    Ciphertext layout: `nonce(12 bytes) || aesgcm_ciphertext`.
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_LEN:
            raise ValueError(f"StaticKeyTotpEncryptor expects a {_KEY_LEN}-byte key")
        self._aead = AESGCM(key)

    @classmethod
    def from_env(cls, env_var: str = "IDENTITY_TOTP_ENCRYPT_KEY") -> StaticKeyTotpEncryptor:
        raw = os.environ.get(env_var)
        if not raw:
            raise RuntimeError(f"{env_var} env var is required for the V1 TOTP encryptor")
        return cls.from_passphrase(raw)

    @classmethod
    def from_passphrase(cls, passphrase: str) -> StaticKeyTotpEncryptor:
        return cls(sha256(passphrase.encode("utf-8")).digest())

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(_NONCE_LEN)
        ct = self._aead.encrypt(nonce, plaintext, associated_data=None)
        return nonce + ct

    def decrypt(self, ciphertext: bytes) -> bytes:
        if len(ciphertext) < _NONCE_LEN + 1:
            raise ValueError("ciphertext too short")
        nonce, body = ciphertext[:_NONCE_LEN], ciphertext[_NONCE_LEN:]
        return self._aead.decrypt(nonce, body, associated_data=None)


__all__ = ["StaticKeyTotpEncryptor"]
