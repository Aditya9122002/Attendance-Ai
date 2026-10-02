import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.dependencies import get_session
from app.main import app
from app.models import School, Student
from app.routers import attendance as attendance_router

DAY = "2026-10-01"


@pytest_asyncio.fixture
async def client(session):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def headers(school) -> dict[str, str]:
    return {"X-School-Id": str(school.id)}


async def put_status(client, school, student, status, day=DAY):
    return await client.put(
        f"/students/{student.id}/attendance/{day}",
        json={"status": status},
        headers=headers(school),
    )


async def test_marking_absent_returns_pending_event(client, school, student):
    response = await put_status(client, school, student, "absent")
    assert response.status_code == 200
    assert response.json() == {
        "student_id": str(student.id),
        "attendance_date": DAY,
        "status": "absent",
        "event_status": "pending",
        "correction_notice_owed": False,
    }


async def test_repeating_the_same_request_gives_the_same_result(client, school, student):
    first = await put_status(client, school, student, "absent")
    second = await put_status(client, school, student, "absent")
    assert second.status_code == 200
    assert second.json() == first.json()


async def test_correcting_to_present_cancels_the_pending_event(client, school, student):
    await put_status(client, school, student, "absent")
    response = await put_status(client, school, student, "present")
    assert response.json()["status"] == "present"
    assert response.json()["event_status"] == "cancelled"


async def test_unknown_student_returns_404(client, school):
    response = await client.put(
        f"/students/{uuid.uuid4()}/attendance/{DAY}",
        json={"status": "absent"},
        headers=headers(school),
    )
    assert response.status_code == 404


async def test_student_of_another_school_returns_404(client, session, student):
    other = School(name="Other School")
    session.add(other)
    await session.flush()
    response = await put_status(client, other, student, "absent")
    assert response.status_code == 404


async def test_missing_school_header_returns_401(client, student):
    response = await client.put(
        f"/students/{student.id}/attendance/{DAY}", json={"status": "absent"}
    )
    assert response.status_code == 401


async def test_invalid_status_returns_422(client, school, student):
    response = await put_status(client, school, student, "maybe")
    assert response.status_code == 422


async def test_invalid_date_returns_422(client, school, student):
    response = await put_status(client, school, student, "absent", day="not-a-date")
    assert response.status_code == 422


async def test_insert_race_is_retried_once(client, session, school, student, monkeypatch):
    await session.commit()  # make the fixtures durable so the retry's rollback keeps them
    real = attendance_router.mark_attendance
    calls = []

    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("INSERT", {}, Exception("duplicate"))
        return await real(*args, **kwargs)

    monkeypatch.setattr(attendance_router, "mark_attendance", flaky)
    response = await put_status(client, school, student, "absent")
    assert response.status_code == 200
    assert len(calls) == 2


async def test_day_list_includes_unmarked_students_and_only_this_school(
    client, session, school, student
):
    other_school = School(name="Other School")
    session.add(other_school)
    await session.flush()
    session.add(Student(school_id=other_school.id, name="Hidden", class_name="5", section="A"))
    second = Student(school_id=school.id, name="Zoya Khan", class_name="5", section="A")
    session.add(second)
    await session.flush()
    await put_status(client, school, student, "absent")

    response = await client.get(f"/attendance/{DAY}", headers=headers(school))
    assert response.status_code == 200
    entries = {e["student_name"]: e for e in response.json()}
    assert set(entries) == {"Asha Patil", "Zoya Khan"}
    assert entries["Asha Patil"]["status"] == "absent"
    assert entries["Asha Patil"]["event_status"] == "pending"
    assert entries["Zoya Khan"]["status"] is None
    assert entries["Zoya Khan"]["event_status"] is None
