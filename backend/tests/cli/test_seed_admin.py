"""Seed-admin CLI tests — phase1-admin-002a AC-06.

Patches the SQLAlchemy persistence path with an in-memory user/totp
repository pair so the CLI's UoW orchestration logic is exercised
without spinning up a Postgres testcontainer for every run.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

import pytest
from click.testing import CliRunner

from tests.identity.fakes.fake_repositories import (
    InMemoryTotpSecretRepository,
    InMemoryUserRepository,
)
from vaultchain.cli.scripts import seed_admin as seed_admin_module


@pytest.fixture
def in_memory_state() -> Iterator[tuple[InMemoryUserRepository, InMemoryTotpSecretRepository]]:
    users = InMemoryUserRepository()
    totps = InMemoryTotpSecretRepository()

    @contextlib.asynccontextmanager
    async def _fake_persist(*, user, secret, database_url):  # type: ignore[no-untyped-def]
        if await users.get_by_email(user.email) is not None:
            import click as _click

            raise _click.ClickException(
                f"User with email {user.email!r} already exists; refusing to overwrite."
            )
        await users.add(user)
        await totps.add(secret)
        yield None

    async def _patched_persist(*, user, secret, database_url):  # type: ignore[no-untyped-def]
        async with _fake_persist(user=user, secret=secret, database_url=database_url):
            return None

    original = seed_admin_module._persist
    seed_admin_module._persist = _patched_persist  # type: ignore[assignment]
    try:
        yield users, totps
    finally:
        seed_admin_module._persist = original  # type: ignore[assignment]


def test_happy_path_inserts_admin_and_totp_secret(
    in_memory_state: tuple[InMemoryUserRepository, InMemoryTotpSecretRepository],
) -> None:
    users, totps = in_memory_state
    runner = CliRunner()
    result = runner.invoke(
        seed_admin_module.main,
        [
            "--email",
            "admin@example.com",
            "--password",
            "strong-passphrase-123",
            "--full-name",
            "Demo Admin",
            "--accept-secret-display",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Admin seeded: admin@example.com" in result.output
    assert "otpauth URI: otpauth://" in result.output
    # Backup codes appear (indented two spaces).
    backup_lines = [ln for ln in result.output.splitlines() if ln.startswith("  ")]
    assert len(backup_lines) == 10

    # User row + TOTP secret row inserted.
    found = _find_user_sync(users, "admin@example.com")
    assert found is not None
    assert found.actor_type.value == "admin"
    assert found.password_hash is not None
    assert _has_secret_for(totps, found.id)


def test_duplicate_email_fails_loud(
    in_memory_state: tuple[InMemoryUserRepository, InMemoryTotpSecretRepository],
) -> None:
    users, _ = in_memory_state
    runner = CliRunner()
    args = [
        "--email",
        "admin@example.com",
        "--password",
        "strong-passphrase-123",
        "--accept-secret-display",
    ]
    first = runner.invoke(seed_admin_module.main, args)
    assert first.exit_code == 0

    second = runner.invoke(seed_admin_module.main, args)
    assert second.exit_code != 0
    assert "already exists" in second.output


def test_short_password_rejected(
    in_memory_state: tuple[InMemoryUserRepository, InMemoryTotpSecretRepository],
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        seed_admin_module.main,
        [
            "--email",
            "admin@example.com",
            "--password",
            "short",
            "--accept-secret-display",
        ],
    )
    assert result.exit_code != 0


def test_confirmation_prompt_aborts_when_no_confirm(
    in_memory_state: tuple[InMemoryUserRepository, InMemoryTotpSecretRepository],
) -> None:
    runner = CliRunner()
    result = runner.invoke(
        seed_admin_module.main,
        [
            "--email",
            "admin@example.com",
            "--password",
            "strong-passphrase-123",
        ],
        input="n\n",
    )
    assert result.exit_code != 0


def _find_user_sync(repo: InMemoryUserRepository, email: str) -> Any | None:
    """Sync helper: peek directly into the in-memory dict to avoid asyncio."""
    for user in repo._by_id.values():
        if user.email == email:
            return user
    return None


def _has_secret_for(repo: InMemoryTotpSecretRepository, user_id: Any) -> bool:
    return user_id in repo._by_user
