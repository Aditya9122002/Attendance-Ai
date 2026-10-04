from datetime import date

from sqlalchemy import func, select

from app.attendance_service import mark_attendance, release_for_retry
from app.call_service import MAX_ATTEMPTS, StartResult, start_call
from app.conversation import ConversationState, Step
from app.models import (
    AbsenceEvent,
    AbsenceEventStatus,
    AttendanceStatus,
    CallAttempt,
    CallAttemptStatus,
    Guardian,
    StudentGuardian,
)

DAY = date(2026, 10, 1)


async def pending_event(session, school, student) -> AbsenceEvent:
    marked = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    return marked.event


async def link_guardian(
    session, school, student, *, primary=True, opted_out=False, language="en", name="Mr. Patil"
) -> Guardian:
    guardian = Guardian(
        school_id=school.id,
        name=name,
        phone="+919800000001",
        language=language,
        opted_out=opted_out,
    )
    session.add(guardian)
    await session.flush()
    session.add(
        StudentGuardian(
            school_id=school.id,
            student_id=student.id,
            guardian_id=guardian.id,
            is_primary=primary,
        )
    )
    await session.flush()
    return guardian


async def count_attempts(session) -> int:
    return await session.scalar(select(func.count()).select_from(CallAttempt))


async def finish_attempts_and_release(session, event) -> None:
    """Pretend the earlier calls ended without a result, as the orchestrator will."""
    for attempt in (await session.scalars(select(CallAttempt))).all():
        attempt.status = CallAttemptStatus.FINISHED.value
    await session.flush()
    assert await release_for_retry(session, event.id) is True


async def test_a_pending_event_with_a_primary_guardian_starts_a_call(session, school, student):
    event = await pending_event(session, school, student)
    guardian = await link_guardian(session, school, student)

    started = await start_call(session, event.id)

    assert started.result == StartResult.STARTED
    call = started.call
    assert call.event_id == event.id
    assert call.to_phone == guardian.phone
    assert event.status == AbsenceEventStatus.DIALING

    attempt = await session.get(CallAttempt, call.attempt_id)
    assert attempt.attempt_number == 1
    assert attempt.status == CallAttemptStatus.IN_PROGRESS
    assert attempt.turn_count == 0
    assert attempt.school_id == school.id
    assert ConversationState.model_validate_json(attempt.state_json).step == Step.IDENTITY


async def test_the_first_line_names_the_school_and_guardian_but_not_the_child(
    session, school, student
):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student)

    call = (await start_call(session, event.id)).call

    assert school.name in call.first_line
    assert "Mr. Patil" in call.first_line
    assert "Asha" not in call.first_line
    assert "Patil" not in call.first_line.replace("Mr. Patil", "")


async def test_only_the_students_first_name_goes_into_the_context(session, school, student):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student)

    call = (await start_call(session, event.id)).call

    assert student.name == "Asha Patil"
    assert call.context.student_name == "Asha"
    assert call.context.school_name == school.name
    assert call.context.guardian_name == "Mr. Patil"


async def test_a_student_with_a_blank_name_is_called_your_child(session, school, student):
    student.name = "   "
    await session.flush()
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student)

    call = (await start_call(session, event.id)).call

    assert call.context.student_name == "your child"


async def test_an_unsupported_guardian_language_falls_back_to_english(session, school, student):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student, language="mr")

    call = (await start_call(session, event.id)).call

    assert call.context.language == "mr"
    assert call.first_line.startswith("Hello, this is an automated assistant")


async def test_an_unknown_event_cannot_be_started(session, school, student):
    import uuid

    started = await start_call(session, uuid.uuid4())
    assert started.result == StartResult.NOT_AVAILABLE
    assert started.call is None
    assert await count_attempts(session) == 0


async def test_a_cancelled_event_is_not_started_and_stays_cancelled(session, school, student):
    await pending_event(session, school, student)
    await link_guardian(session, school, student)
    cancelled = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.PRESENT)

    started = await start_call(session, cancelled.event.id)

    assert started.result == StartResult.NOT_AVAILABLE
    assert cancelled.event.status == AbsenceEventStatus.CANCELLED
    assert await count_attempts(session) == 0


async def test_an_event_cannot_be_started_twice(session, school, student):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student)

    first = await start_call(session, event.id)
    second = await start_call(session, event.id)

    assert first.result == StartResult.STARTED
    assert second.result == StartResult.NOT_AVAILABLE
    assert await count_attempts(session) == 1


async def test_no_guardian_means_a_person_follows_up_and_no_attempt_is_created(
    session, school, student
):
    event = await pending_event(session, school, student)

    started = await start_call(session, event.id)

    assert started.result == StartResult.NO_GUARDIAN
    assert started.call is None
    assert event.status == AbsenceEventStatus.NEEDS_HUMAN
    assert await count_attempts(session) == 0


async def test_a_guardian_who_is_not_primary_is_not_called(session, school, student):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student, primary=False)

    started = await start_call(session, event.id)

    assert started.result == StartResult.NO_GUARDIAN
    assert event.status == AbsenceEventStatus.NEEDS_HUMAN


async def test_a_guardian_who_opted_out_is_never_called(session, school, student):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student, opted_out=True)

    started = await start_call(session, event.id)

    assert started.result == StartResult.NO_GUARDIAN
    assert started.call is None
    assert event.status == AbsenceEventStatus.NEEDS_HUMAN
    assert await count_attempts(session) == 0


async def test_a_retry_after_an_unfinished_call_gets_the_next_attempt_number(
    session, school, student
):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student)
    first = (await start_call(session, event.id)).call
    await finish_attempts_and_release(session, event)

    second = (await start_call(session, event.id)).call

    assert second.attempt_id != first.attempt_id
    attempt = await session.get(CallAttempt, second.attempt_id)
    assert attempt.attempt_number == 2
    assert event.status == AbsenceEventStatus.DIALING


async def test_after_the_allowed_attempts_a_person_follows_up_instead_of_another_call(
    session, school, student
):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student)
    for _ in range(MAX_ATTEMPTS):
        assert (await start_call(session, event.id)).result == StartResult.STARTED
        await finish_attempts_and_release(session, event)

    started = await start_call(session, event.id)

    assert started.result == StartResult.TOO_MANY_ATTEMPTS
    assert started.call is None
    assert event.status == AbsenceEventStatus.NEEDS_HUMAN
    assert await count_attempts(session) == MAX_ATTEMPTS


async def test_the_attempt_limit_can_be_set_by_the_caller(session, school, student):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student)
    assert (await start_call(session, event.id, max_attempts=1)).result == StartResult.STARTED
    await finish_attempts_and_release(session, event)

    started = await start_call(session, event.id, max_attempts=1)

    assert started.result == StartResult.TOO_MANY_ATTEMPTS
