"""``MagicLinkTokenGenerator`` adapter — wraps ``secrets.token_urlsafe``.

32 bytes of randomness ⇒ ~256 bits ⇒ collision-resistant; the URL form
is what the user clicks, the sha256 hash is what the DB stores.
"""

from __future__ import annotations

import secrets

#: 32 bytes ⇒ 43 base64-urlsafe characters (no padding). 256 bits of
#: entropy is 'never collide' for any reasonable retention.
TOKEN_BYTES = 32


class SecretsMagicLinkTokenGenerator:
    def generate(self) -> str:
        return secrets.token_urlsafe(TOKEN_BYTES)


__all__ = ["TOKEN_BYTES", "SecretsMagicLinkTokenGenerator"]
