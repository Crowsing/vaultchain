"""Shared domain primitives — DomainError hierarchy, Money, Address, etc.

Phase 1 briefs add `Money` and `Address`; this module currently exports the
error hierarchy from `phase1-shared-005`.
"""

from vaultchain.shared.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionError,
    ValidationError,
)

__all__ = [
    "ConflictError",
    "DomainError",
    "NotFoundError",
    "PermissionError",
    "ValidationError",
]
