"""Domain-layer tests for the `DomainError` hierarchy.

Covers AC-phase1-shared-005-02 and -03 — status_code mapping per subclass and
details round-tripping. Plus AC-phase1-shared-005 "code regex enforcement"
(implementation note in the brief, not a numbered AC, but still required).
"""

from __future__ import annotations

from http import HTTPStatus

import pytest

from vaultchain.shared.domain.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionError,
    ValidationError,
)


def test_validation_error_has_status_400() -> None:
    """AC-02: ValidationError → 400 with `validation.<subcode>` code."""
    err = ValidationError()
    assert err.status_code == HTTPStatus.BAD_REQUEST
    assert err.code.startswith("validation.")
    assert err.message == "Request input is invalid."


def test_conflict_error_round_trip_details() -> None:
    """AC-03: details dict survives construction unchanged."""
    payload = {"current_version": 3, "expected_version": 2}
    err = ConflictError(details=payload)
    assert err.status_code == HTTPStatus.CONFLICT
    assert err.details == payload
    # Defensive copy — mutating the supplied dict afterwards must not bleed in.
    payload["current_version"] = 99
    assert err.details["current_version"] == 3


def test_not_found_error_status_404() -> None:
    err = NotFoundError()
    assert err.status_code == HTTPStatus.NOT_FOUND
    assert err.code == "common.not_found"


def test_permission_error_status_403() -> None:
    err = PermissionError()
    assert err.status_code == HTTPStatus.FORBIDDEN
    assert err.code == "common.permission_denied"


def test_default_message_used_when_omitted() -> None:
    assert ValidationError().message == ValidationError.default_message
    assert NotFoundError("custom").message == "custom"


def test_code_format_dotted_lowercase() -> None:
    """Implementation Notes: codes match `{context}.{condition}` snake_case."""

    class GoodError(DomainError):
        code = "context.valid_condition"
        status_code = 418

    assert GoodError().code == "context.valid_condition"

    with pytest.raises(TypeError) as excinfo:

        class BadError(DomainError):
            code = "validationInvalid"  # camelCase — disallowed
            status_code = 400

    assert "BadError" in str(excinfo.value)
    assert "validationInvalid" in str(excinfo.value)


def test_abstract_intermediate_subclass_allowed() -> None:
    """An intermediate subclass with empty code skips the regex check."""

    class AbstractMid(DomainError):
        # Deliberately blank — this layer exists for typing/grouping only.
        pass

    class ConcreteFromMid(AbstractMid):
        code = "context.something"
        status_code = 422

    assert ConcreteFromMid().code == "context.something"
