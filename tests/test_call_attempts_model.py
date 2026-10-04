from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.attendance_service import mark_attendance, try_start_dialing
from app.conversation import ConversationState
from app.models import (
    AttendanceStatus,
    CallAttempt,
    CallAttemptStatus,
    School,
)

DAY = date(2026, 10, 1)


async def make_event(session, school, student):
    marked = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    assert await try_start_dialing(session, marked.event.id) is True
    return marked.event


def make_attempt(event, **overrides) -> CallAttempt:
    data = {
        "school_id": event.school_id,
        "absence_event_id": event.id,
        "attempt_number": 1,
        "state_json": ConversationState().model_dump_json(),
    }
    data.update(overrides)
    return CallAttempt(**data)


async def test_a_new_attempt_starts_in_progress_with_no_turns_and_no_outcome(
    session, school, student
):
    event = await make_event(session, school, student)
    attempt = make_attempt(event)
    session.add(attempt)
    await session.flush()
    assert attempt.status == CallAttemptStatus.IN_PROGRESS
    assert attempt.turn_count == 0
    assert attempt.outcome is None
    assert attempt.ended_at is None


async def test_the_stored_state_round_trips_through_json(session, school, student):
    event = await make_event(session, school, student)
    attempt = make_attempt(event, state_json=ConversationState(unclear_count=1).model_dump_json())
    session.add(attempt)
    await session.flush()
    restored = ConversationState.model_validate_json(attempt.state_json)
    assert restored.unclear_count == 1


async def test_database_rejects_an_unknown_attempt_status(session, school, student):
    event = await make_event(session, school, student)
    session.add(make_attempt(event, status="paused"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_database_rejects_an_unknown_outcome(session, school, student):
    event = await make_event(session, school, student)
    session.add(make_attempt(event, outcome="vanished"))
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize(("field", "value"), [("attempt_number", 0), ("turn_count", -1)])
async def test_database_rejects_out_of_range_counters(session, school, student, field, value):
    event = await make_event(session, school, student)
    session.add(make_attempt(event, **{field: value}))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_database_rejects_a_repeated_attempt_number_for_one_event(session, school, student):
    event = await make_event(session, school, student)
    session.add(make_attempt(event, status=CallAttemptStatus.FINISHED.value))
    await session.flush()
    session.add(make_attempt(event, status=CallAttemptStatus.FINISHED.value))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_database_rejects_two_calls_in_progress_for_one_event(session, school, student):
    event = await make_event(session, school, student)
    session.add(make_attempt(event, attempt_number=1))
    await session.flush()
    session.add(make_attempt(event, attempt_number=2))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_a_second_attempt_is_allowed_once_the_first_has_finished(session, school, student):
    event = await make_event(session, school, student)
    session.add(make_attempt(event, attempt_number=1, status=CallAttemptStatus.FINISHED.value))
    await session.flush()
    session.add(make_attempt(event, attempt_number=2))
    await session.flush()


async def test_database_rejects_an_attempt_that_names_another_school(session, school, student):
    event = await make_event(session, school, student)
    other = School(name="Other School")
    session.add(other)
    await session.flush()
    session.add(make_attempt(event, school_id=other.id))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_attempt_table_stores_no_transcript_or_reply_text():
    names = {c.name for c in CallAttempt.__table__.columns}
    assert not {n for n in names if "transcript" in n or "reply" in n}
