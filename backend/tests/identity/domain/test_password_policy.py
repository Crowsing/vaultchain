"""PasswordPolicy domain VO tests — phase1-admin-002a AC-06."""

from __future__ import annotations

import pytest

from vaultchain.identity.domain.value_objects import (
    ADMIN_PASSWORD_MIN_LENGTH,
    ActorType,
    PasswordPolicy,
)
from vaultchain.shared.domain.errors import ValidationError


def test_strong_password_passes() -> None:
    PasswordPolicy().validate("correcthorsebatterystaple!1")


def test_default_min_length_is_admin_constant() -> None:
    assert PasswordPolicy().min_length == ADMIN_PASSWORD_MIN_LENGTH


def test_short_password_rejected() -> None:
    with pytest.raises(ValidationError):
        PasswordPolicy().validate("short")


def test_empty_password_rejected() -> None:
    with pytest.raises(ValidationError):
        PasswordPolicy().validate("")


def test_whitespace_only_rejected() -> None:
    with pytest.raises(ValidationError):
        PasswordPolicy().validate("            ")


def test_actor_type_values() -> None:
    assert ActorType.USER.value == "user"
    assert ActorType.ADMIN.value == "admin"
