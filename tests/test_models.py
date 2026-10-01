import pytest
from app.models import Guardian, School, Student, StudentGuardian
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


async def make_school(session: AsyncSession, name: str = "Demo School") -> School:
    school = School(name=name)
    session.add(school)
    await session.flush()
    return school


async def make_student(session: AsyncSession, school: School) -> Student:
    student = Student(school_id=school.id, name="Asha Patil", class_name="5", section="A")
    session.add(student)
    await session.flush()
    return student


async def make_guardian(
    session: AsyncSession, school: School, phone: str = "+919800000000"
) -> Guardian:
    guardian = Guardian(school_id=school.id, name="Mr. Patil", phone=phone)
    session.add(guardian)
    await session.flush()
    return guardian


async def test_defaults(session):
    school = await make_school(session)
    guardian = await make_guardian(session, school)
    assert school.timezone == "Asia/Kolkata"
    assert school.notify_parent_on_correction is True
    assert guardian.language == "en"
    assert guardian.opted_out is False


async def test_link_guardian_to_student(session):
    school = await make_school(session)
    student = await make_student(session, school)
    guardian = await make_guardian(session, school)
    session.add(
        StudentGuardian(
            school_id=school.id, student_id=student.id, guardian_id=guardian.id, is_primary=True
        )
    )
    await session.commit()
    links = (await session.execute(select(StudentGuardian))).scalars().all()
    assert len(links) == 1


async def test_cannot_link_across_schools(session):
    school_a = await make_school(session, "School A")
    school_b = await make_school(session, "School B")
    student = await make_student(session, school_a)
    guardian = await make_guardian(session, school_b)
    session.add(
        StudentGuardian(school_id=school_a.id, student_id=student.id, guardian_id=guardian.id)
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_only_one_primary_guardian_per_student(session):
    school = await make_school(session)
    student = await make_student(session, school)
    first = await make_guardian(session, school)
    second = await make_guardian(session, school, phone="+919811111111")
    session.add(
        StudentGuardian(
            school_id=school.id, student_id=student.id, guardian_id=first.id, is_primary=True
        )
    )
    await session.flush()
    session.add(
        StudentGuardian(
            school_id=school.id, student_id=student.id, guardian_id=second.id, is_primary=True
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_phone_must_start_with_plus(session):
    school = await make_school(session)
    session.add(Guardian(school_id=school.id, name="No Plus", phone="9800000000"))
    with pytest.raises(IntegrityError):
        await session.flush()
