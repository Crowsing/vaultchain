"""Domain error hierarchy.

Every value movement, state transition, or external call surface in VaultChain
raises a `DomainError` subclass on failure. The delivery layer's exception
handlers (`vaultchain.shared.delivery.error_handlers`) translate them into the
canonical HTTP envelope:

    {
      "error": {
        "code": "<context>.<condition>",
        "message": "<human-readable English>",
        "details": {...},
        "request_id": "req_...",
        "documentation_url": "https://docs.vaultchain.example/errors/<code>"
      }
    }

This module ships the base class plus four placeholder subclasses called out
in `phase1-shared-005`. Concrete per-context error subclasses live in their
owning context (e.g. `vaultchain.identity.domain.errors.MagicLinkExpired`).
"""

from __future__ import annotations

import re
from http import HTTPStatus
from typing import Any, ClassVar

# {context}.{condition} — dotted, lowercase, snake_case. Enforced at class
# definition time so misformed codes fail at import, not at the bug bar.
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class DomainError(Exception):
    """Base class for every domain-modelled error.

    Subclasses MUST set:
        code:        machine-readable identifier matching `{context}.{condition}`
        status_code: HTTP status integer per Section 4 mapping rules

    Optional:
        default_message: fallback human-readable English message; instance
                         constructor's `message` argument overrides.
    """

    code: ClassVar[str] = ""
    status_code: ClassVar[int] = HTTPStatus.INTERNAL_SERVER_ERROR
    default_message: ClassVar[str] = "Something went wrong."

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Allow intermediate abstract subclasses to skip the enforcement by
        # leaving `code` blank — concrete subclasses MUST set a valid code.
        if cls.code == "":
            return
        if not _CODE_RE.match(cls.code):
            raise TypeError(
                f"DomainError subclass {cls.__module__}.{cls.__qualname__} has "
                f"invalid code {cls.code!r}; must match {_CODE_RE.pattern}"
            )

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message: str = message if message is not None else self.default_message
        self.details: dict[str, Any] = dict(details) if details else {}
        super().__init__(self.message)


class ValidationError(DomainError):
    """Inputs failed validation — wrong shape, type, or basic semantics."""

    code: ClassVar[str] = "validation.invalid_input"
    status_code: ClassVar[int] = HTTPStatus.BAD_REQUEST
    default_message: ClassVar[str] = "Request input is invalid."


class NotFoundError(DomainError):
    """Resource does not exist (or is invisible to the requester)."""

    code: ClassVar[str] = "common.not_found"
    status_code: ClassVar[int] = HTTPStatus.NOT_FOUND
    default_message: ClassVar[str] = "Resource not found."


class ConflictError(DomainError):
    """Idempotency conflict, optimistic-lock collision, or unique constraint."""

    code: ClassVar[str] = "common.conflict"
    status_code: ClassVar[int] = HTTPStatus.CONFLICT
    default_message: ClassVar[str] = "Request conflicts with current state."


class PermissionError(DomainError):
    """Caller is authenticated but not authorised for this action."""

    code: ClassVar[str] = "common.permission_denied"
    status_code: ClassVar[int] = HTTPStatus.FORBIDDEN
    default_message: ClassVar[str] = "Permission denied."


class StaleAggregate(ConflictError):
    """Optimistic-lock collision: aggregate version moved between read and write."""

    code: ClassVar[str] = "concurrency.stale_aggregate"
    status_code: ClassVar[int] = HTTPStatus.CONFLICT
    default_message: ClassVar[str] = (
        "Aggregate was modified by another writer; retry with the latest version."
    )


__all__ = [
    "ConflictError",
    "DomainError",
    "NotFoundError",
    "PermissionError",
    "StaleAggregate",
    "ValidationError",
]
