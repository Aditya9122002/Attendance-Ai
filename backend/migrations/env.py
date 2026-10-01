"""Alembic environment: runs migrations against the app's async engine."""

import asyncio

from alembic import context
from sqlalchemy.engine import Connection

import app.models  # noqa: F401  (registers the tables on Base.metadata)
from app.config import get_settings
from app.database import Base, create_engine

config = context.config
target_metadata = Base.metadata


def _database_url() -> str:
    """Use an explicitly configured URL (tests) or fall back to application settings."""
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting to a database."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect with the async engine and apply migrations."""
    engine = create_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
