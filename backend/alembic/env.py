"""Alembic async migration runner.

Phase 1 briefs (specifically phase1-shared-003) populate target_metadata.
For now this is a no-op runner that lets `alembic upgrade head` succeed
on an empty migration set.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Phase 1: replace with `from vaultchain.shared.infra.database import Base`
target_metadata = None

# Resolve DATABASE_URL with password injection.
#
# Prod compose passes a password-less DATABASE_URL plus a docker secret at
# /run/secrets/postgres_password. We need to splice the file's contents into
# the URL so asyncpg can authenticate.
#
# Strategy (defense-in-depth):
#   1. Prefer freshly-instantiated `Settings` (NOT get_settings() singleton —
#      tests monkeypatch DATABASE_URL between alembic calls and the cache
#      would freeze the first URL). Settings._inject_db_password handles
#      the password merge.
#   2. If Settings can't import or required fields are missing (e.g., minimal
#      alembic shells), fall back to env var + direct file read.


def _resolve_db_url() -> str:
    try:
        from vaultchain.config import Settings

        return Settings().database_url
    except Exception as exc:
        # Alembic must boot even when Settings can't load (e.g., a minimal
        # alembic shell without SECRET_KEY); the env-var path still gets us
        # a working URL with password injected from /run/secrets/.
        print(f"[alembic] Settings load failed ({exc}); falling back", file=sys.stderr)

    raw = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url") or "")
    if not raw:
        return raw
    parsed = make_url(raw)
    if parsed.password:
        return raw
    pw_file = Path("/run/secrets/postgres_password")
    if pw_file.is_file():
        password = pw_file.read_text().strip()
        if password:
            return parsed.set(password=password).render_as_string(hide_password=False)
    return raw


db_url = _resolve_db_url()
config.set_main_option("sqlalchemy.url", db_url)

# Diagnostic (password is masked) — helps debug a future deploy that fails
# at this step without leaking the actual secret to CI logs.
_parsed = make_url(db_url) if db_url else None
if _parsed is not None:
    print(
        f"[alembic] sqlalchemy.url={_parsed.render_as_string(hide_password=True)} "
        f"has_password={'yes' if _parsed.password else 'no'}",
        file=sys.stderr,
    )


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
