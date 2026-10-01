from sqlalchemy import text

from app.database import create_engine, create_session_factory


async def test_session_can_run_a_query():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with create_session_factory(engine)() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await engine.dispose()


async def test_sqlite_foreign_keys_are_enforced():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
    finally:
        await engine.dispose()
