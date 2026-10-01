"""Async SQLAlchemy engine, session factory and declarative base."""

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Parent class for every ORM model."""


def create_engine(database_url: str) -> AsyncEngine:
    """Create an async engine; on SQLite, turn on foreign-key enforcement."""
    engine = create_async_engine(database_url)

    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return a session factory. expire_on_commit=False avoids lazy reloads that break async."""
    return async_sessionmaker(engine, expire_on_commit=False)
