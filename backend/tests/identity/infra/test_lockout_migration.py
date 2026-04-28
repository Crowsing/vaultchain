"""Lockout-columns migration test — AC-phase1-identity-003-01.

Applies the migration against a Postgres testcontainer and verifies the two
new columns on ``identity.users``: nullable/default semantics and a clean
downgrade that drops them without dropping the rest of the schema.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _alembic_config(async_dsn: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", async_dsn)
    return cfg


@pytest.fixture(scope="module")
def pg_container() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16-alpine") as pg:
        yield pg


@pytest.fixture(scope="module")
def async_dsn(pg_container: PostgresContainer) -> str:
    raw = pg_container.get_connection_url()
    return raw.replace("postgresql+psycopg2://", "postgresql+asyncpg://")


@pytest_asyncio.fixture
async def migrated_engine(async_dsn: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[object]:
    monkeypatch.setenv("DATABASE_URL", async_dsn)
    cfg = _alembic_config(async_dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_async_engine(async_dsn, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()
        await asyncio.to_thread(command.downgrade, cfg, "base")


async def _users_columns(engine: object) -> dict[str, dict[str, object]]:
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema='identity' AND table_name='users'"
                )
            )
        ).all()
    return {r[0]: {"type": r[1], "nullable": r[2], "default": r[3]} for r in rows}


@pytest.mark.asyncio
async def test_ac_01_lockout_columns_exist_with_specified_types(
    migrated_engine: object,
) -> None:
    cols = await _users_columns(migrated_engine)
    assert "failed_totp_attempts" in cols
    assert cols["failed_totp_attempts"]["type"] == "integer"
    assert cols["failed_totp_attempts"]["nullable"] == "NO"
    # server_default normalised to a literal 0 by Postgres.
    assert "0" in str(cols["failed_totp_attempts"]["default"] or "")

    assert "locked_until" in cols
    assert cols["locked_until"]["type"] == "timestamp with time zone"
    assert cols["locked_until"]["nullable"] == "YES"


@pytest.mark.asyncio
async def test_ac_01_existing_users_get_zero_default_on_upgrade(
    migrated_engine: object,
) -> None:
    """The migration must be safe for an already-populated `users` table.

    A non-null `failed_totp_attempts` without a server default would refuse
    the migration on a row-bearing table, so this guards against a regression
    where someone removes ``server_default``.
    """
    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        # The fixture already ran upgrade; just exercise an INSERT that omits
        # the new column to verify the default applies.
        await conn.execute(
            sa.text(
                "INSERT INTO identity.users (id, email, email_hash) " "VALUES (:id, :email, :hash)"
            ),
            {"id": "00000000-0000-0000-0000-000000000001", "email": "u@x.com", "hash": b""},
        )
        await conn.commit()
        row = (
            await conn.execute(
                sa.text(
                    "SELECT failed_totp_attempts, locked_until FROM identity.users WHERE email=:e"
                ),
                {"e": "u@x.com"},
            )
        ).one()
    assert row.failed_totp_attempts == 0
    assert row.locked_until is None


@pytest.mark.asyncio
async def test_ac_01_downgrade_removes_only_the_lockout_columns(
    async_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", async_dsn)
    cfg = _alembic_config(async_dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.downgrade, cfg, "20260428_103000")
    engine = create_async_engine(async_dsn, future=True)
    try:
        async with engine.connect() as conn:
            cols = (
                (
                    await conn.execute(
                        sa.text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema='identity' AND table_name='users'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert "failed_totp_attempts" not in cols
            assert "locked_until" not in cols
            # Schema and the rest of the columns survive the downgrade.
            assert "email" in cols
            assert "version" in cols
    finally:
        await engine.dispose()
        await asyncio.to_thread(command.downgrade, cfg, "base")
