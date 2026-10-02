import pytest_asyncio

import app.models  # noqa: F401  (registers the tables on Base.metadata)
from app.database import Base, create_engine, create_session_factory
from app.models import School, Student


@pytest_asyncio.fixture
async def session():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with create_session_factory(engine)() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def school(session):
    school = School(name="Demo School")
    session.add(school)
    await session.flush()
    return school


@pytest_asyncio.fixture
async def student(session, school):
    student = Student(school_id=school.id, name="Asha Patil", class_name="5", section="A")
    session.add(student)
    await session.flush()
    return student
