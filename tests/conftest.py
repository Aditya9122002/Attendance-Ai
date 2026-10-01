import pytest_asyncio

import app.models  # noqa: F401  (registers the tables on Base.metadata)
from app.database import Base, create_engine, create_session_factory


@pytest_asyncio.fixture
async def session():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as session:
        yield session
    await engine.dispose()
