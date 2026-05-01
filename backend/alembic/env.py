"""Alembic async migration runner.

Phase 1 briefs (specifically phase1-shared-003) populate target_metadata.
For now this is a no-op runner that lets `alembic upgrade head` succeed
on an empty migration set.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Phase 1: replace with `from vaultchain.shared.infra.database import Base`
target_metadata = None

# Use a freshly-instantiated Settings (NOT the get_settings() singleton) so
# docker-compose's password-via-secret-file pattern works:
# Settings.postgres_password is read from /run/secrets/postgres_password and
# spliced into database_url by `_inject_db_password`. Tests that monkeypatch
# DATABASE_URL between alembic invocations need a fresh read each time;
# get_settings() caches the first URL it sees.
#
# Falls back to the raw env var if Settings can't import or required fields
# are missing (e.g., minimal alembic shells without SECRET_KEY).
try:
    from vaultchain.config import Settings

    db_url = Settings().database_url
except Exception:
    db_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
