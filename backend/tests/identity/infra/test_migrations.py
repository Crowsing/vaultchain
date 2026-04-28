"""Migration tests — AC-phase1-identity-001-01, -02.

Applies the migration against a Postgres testcontainer and verifies schema,
columns, constraints, FKs, indexes, and clean downgrade.
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


async def _columns(engine: object, schema: str, table: str) -> dict[str, dict[str, object]]:
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema=:s AND table_name=:t"
                ),
                {"s": schema, "t": table},
            )
        ).all()
    return {r[0]: {"type": r[1], "nullable": r[2], "default": r[3]} for r in rows}


@pytest.mark.asyncio
async def test_ac_01_creates_identity_schema(migrated_engine: object) -> None:
    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        schemas = (
            (await conn.execute(sa.text("SELECT schema_name FROM information_schema.schemata")))
            .scalars()
            .all()
        )
    assert "identity" in schemas


@pytest.mark.asyncio
async def test_ac_01_users_table_columns_match_spec(migrated_engine: object) -> None:
    cols = await _columns(migrated_engine, "identity", "users")
    expected = {
        "id",
        "email",
        "email_hash",
        "status",
        "kyc_tier",
        "version",
        "created_at",
        "updated_at",
        # Added by phase1-identity-003 lockout-columns migration; head includes both.
        "failed_totp_attempts",
        "locked_until",
    }
    assert set(cols) == expected
    assert cols["email"]["nullable"] == "NO"
    assert cols["email_hash"]["nullable"] == "NO"
    assert cols["status"]["nullable"] == "NO"
    assert cols["kyc_tier"]["nullable"] == "NO"
    assert cols["version"]["nullable"] == "NO"
    assert cols["updated_at"]["nullable"] == "YES"


@pytest.mark.asyncio
async def test_ac_01_users_status_check_constraint(migrated_engine: object) -> None:
    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype='c' AND conrelid='identity.users'::regclass"
                )
            )
        ).all()
    assert any(r[0] == "ck_users_status" for r in rows)


@pytest.mark.asyncio
async def test_ac_01_users_email_unique(migrated_engine: object) -> None:
    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype='u' AND conrelid='identity.users'::regclass"
                )
            )
        ).all()
    assert any("email" in r[0] for r in rows)


@pytest.mark.asyncio
async def test_ac_01_sessions_columns_and_fk(migrated_engine: object) -> None:
    cols = await _columns(migrated_engine, "identity", "sessions")
    expected = {
        "id",
        "user_id",
        "refresh_token_hash",
        "created_at",
        "last_used_at",
        "expires_at",
        "revoked_at",
        "user_agent",
        "ip_inet",
        "version",
    }
    assert set(cols) == expected
    assert cols["revoked_at"]["nullable"] == "YES"
    assert cols["ip_inet"]["nullable"] == "YES"

    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        fks = (
            await conn.execute(
                sa.text(
                    "SELECT confrelid::regclass::text "
                    "FROM pg_constraint "
                    "WHERE contype='f' AND conrelid='identity.sessions'::regclass"
                )
            )
        ).all()
    assert any("identity.users" in r[0] for r in fks)


@pytest.mark.asyncio
async def test_ac_01_sessions_refresh_token_hash_unique(migrated_engine: object) -> None:
    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype='u' AND conrelid='identity.sessions'::regclass"
                )
            )
        ).all()
    assert any("refresh_token_hash" in r[0] for r in rows)


@pytest.mark.asyncio
async def test_ac_01_magic_links_columns_and_check(migrated_engine: object) -> None:
    cols = await _columns(migrated_engine, "identity", "magic_links")
    expected = {
        "id",
        "user_id",
        "token_hash",
        "mode",
        "created_at",
        "expires_at",
        "consumed_at",
    }
    assert set(cols) == expected

    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype='c' AND conrelid='identity.magic_links'::regclass"
                )
            )
        ).all()
    assert any(r[0] == "ck_magic_links_mode" for r in rows)


@pytest.mark.asyncio
async def test_ac_01_totp_secrets_columns_and_user_id_unique(migrated_engine: object) -> None:
    cols = await _columns(migrated_engine, "identity", "totp_secrets")
    expected = {
        "id",
        "user_id",
        "secret_encrypted",
        "backup_codes_hashed",
        "enrolled_at",
        "last_verified_at",
    }
    assert set(cols) == expected

    engine = migrated_engine
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE contype='u' AND conrelid='identity.totp_secrets'::regclass"
                )
            )
        ).all()
    assert any("user_id" in r[0] for r in rows)


@pytest.mark.asyncio
async def test_ac_02_downgrade_removes_all_tables_and_schema(
    async_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", async_dsn)
    cfg = _alembic_config(async_dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.downgrade, cfg, "base")
    engine = create_async_engine(async_dsn, future=True)
    try:
        async with engine.connect() as conn:
            schemas = (
                (await conn.execute(sa.text("SELECT schema_name FROM information_schema.schemata")))
                .scalars()
                .all()
            )
            assert "identity" not in schemas
            tables = (
                await conn.execute(
                    sa.text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema='identity'"
                    )
                )
            ).all()
            assert tables == []
    finally:
        await engine.dispose()
