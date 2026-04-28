"""Identity-context value objects.

`Email` lives here (not `shared/domain/`) because only the identity context
uses it. Promote to `shared/` only if a second context needs it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from vaultchain.shared.domain.errors import ValidationError

# Pragmatic RFC-5321 subset: local-part + @ + domain.tld. Reject obviously
# malformed; do not attempt MX validation.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_MAX_LOCAL = 64
_MAX_TOTAL = 254


@dataclass(frozen=True, slots=True)
class Email:
    """Normalized + validated email value object."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip().lower()
        if not normalized:
            raise ValidationError(
                "email cannot be empty",
                details={"field": "email", "rule": "required"},
            )
        if len(normalized) > _MAX_TOTAL:
            raise ValidationError(
                f"email exceeds {_MAX_TOTAL} characters",
                details={"field": "email", "rule": "max_length"},
            )
        local, _, _domain = normalized.partition("@")
        if len(local) > _MAX_LOCAL:
            raise ValidationError(
                f"email local-part exceeds {_MAX_LOCAL} characters",
                details={"field": "email", "rule": "local_max_length"},
            )
        if not _EMAIL_RE.match(normalized):
            raise ValidationError(
                "email is not a valid address",
                details={"field": "email", "rule": "format"},
            )
        # frozen dataclass — bypass setattr restriction.
        object.__setattr__(self, "value", normalized)

    def hash_blake2b(self) -> bytes:
        """Hash for V2 search-without-decrypt scenarios; unused in V1 reads."""
        return hashlib.blake2b(self.value.encode("utf-8"), digest_size=32).digest()


__all__ = ["Email"]
