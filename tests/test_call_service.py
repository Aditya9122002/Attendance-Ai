import json
import uuid
from datetime import date

import pytest
from sqlalchemy import delete, func, select, update

from app.attendance_service import mark_attendance, release_for_retry
from app.call_service import (
    MAX_ATTEMPTS,
    AttemptNotFoundError,
    CallDataError,
    StartResult,
    TurnConflictError,
    handle_parent_reply,
    start_call,
)
from app.conversation import ConversationState, Outcome, Step
from app.llm.base import LlmError
from app.llm.fake import ScriptedLlmClient
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
TODAY = date(2026, 10, 2)


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


# ---- handle_parent_reply -------------------------------------------------------------------


def intent(name: str, has_question: bool = False) -> str:
    return json.dumps({"intent": name, "has_question": has_question})


def extraction(**overrides) -> str:
    data = {
        "reason": "illness",
        "expected_return_date": "2026-10-05",
        "needs_human_followup": False,
        "confidence": 0.9,
    }
    data.update(overrides)
    return json.dumps(data)


async def call_in_progress(session, school, student):
    event = await pending_event(session, school, student)
    await link_guardian(session, school, student)
    started = await start_call(session, event.id)
    assert started.result == StartResult.STARTED
    return event, started.call.attempt_id


async def stored_state(session, attempt_id) -> ConversationState:
    attempt = await session.get(CallAttempt, attempt_id)
    return ConversationState.model_validate_json(attempt.state_json)


async def test_a_reply_moves_the_call_on_and_saves_the_state(session, school, student):
    _, attempt_id = await call_in_progress(session, school, student)

    result = await handle_parent_reply(
        session, attempt_id, "Yes speaking", ScriptedLlmClient(intent("yes")), TODAY
    )

    assert result.ended is False
    assert result.outcome is None
    assert "Asha" in result.say  # the child is named only after identity is confirmed
    assert (await stored_state(session, attempt_id)).step == Step.REASON
    attempt = await session.get(CallAttempt, attempt_id)
    assert attempt.turn_count == 1
    assert attempt.status == CallAttemptStatus.IN_PROGRESS
    assert attempt.outcome is None


async def test_a_whole_call_ends_completed_with_the_attempt_finished(session, school, student):
    _, attempt_id = await call_in_progress(session, school, student)
    llm = ScriptedLlmClient(
        intent("yes"),  # identity
        intent("answer"),  # reason
        extraction(),
        intent("yes"),  # confirm
    )

    first = await handle_parent_reply(session, attempt_id, "Yes", llm, TODAY)
    second = await handle_parent_reply(session, attempt_id, "He has fever till Sunday", llm, TODAY)
    third = await handle_parent_reply(session, attempt_id, "Yes that is right", llm, TODAY)

    assert [first.ended, second.ended, third.ended] == [False, False, True]
    assert third.outcome == Outcome.COMPLETED
    attempt = await session.get(CallAttempt, attempt_id)
    assert attempt.status == CallAttemptStatus.FINISHED
    assert attempt.outcome == "completed"
    assert attempt.ended_at is not None
    assert attempt.turn_count == 3
    saved = await stored_state(session, attempt_id)
    assert saved.step == Step.ENDED
    assert saved.extraction.reason == "illness"


async def test_the_model_never_sees_a_school_guardian_or_student_name(session, school, student):
    _, attempt_id = await call_in_progress(session, school, student)
    llm = ScriptedLlmClient(intent("yes"), intent("answer"), extraction(), intent("yes"))

    for reply in ("Yes", "He has fever", "Yes"):
        await handle_parent_reply(session, attempt_id, reply, llm, TODAY)

    sent = " ".join(call["system"] + call["user"] for call in llm.calls)
    for name in ("Demo School", "Patil", "Asha"):
        assert name not in sent


async def test_an_opt_out_ends_the_call_as_opted_out(session, school, student):
    _, attempt_id = await call_in_progress(session, school, student)

    result = await handle_parent_reply(
        session, attempt_id, "Do not call me again", ScriptedLlmClient(intent("opt_out")), TODAY
    )

    assert result.ended is True
    assert result.outcome == Outcome.OPTED_OUT
    attempt = await session.get(CallAttempt, attempt_id)
    assert attempt.status == CallAttemptStatus.FINISHED
    assert attempt.outcome == "opted_out"


async def test_a_model_outage_ends_the_call_politely_as_incomplete(session, school, student):
    _, attempt_id = await call_in_progress(session, school, student)

    result = await handle_parent_reply(
        session, attempt_id, "Yes", ScriptedLlmClient(LlmError("down")), TODAY
    )

    assert result.ended is True
    assert result.outcome == Outcome.INCOMPLETE
    assert "technical problem" in result.say
    assert (await session.get(CallAttempt, attempt_id)).outcome == "incomplete"


async def test_silence_repeats_the_question_without_calling_the_model(session, school, student):
    _, attempt_id = await call_in_progress(session, school, student)
    llm = ScriptedLlmClient()

    result = await handle_parent_reply(session, attempt_id, "   ", llm, TODAY)

    assert result.ended is False
    assert llm.calls == []
    saved = await stored_state(session, attempt_id)
    assert saved.step == Step.IDENTITY
    assert saved.unclear_count == 1
    assert (await session.get(CallAttempt, attempt_id)).turn_count == 1


async def test_an_unknown_attempt_is_reported(session, school, student):
    with pytest.raises(AttemptNotFoundError):
        await handle_parent_reply(session, uuid.uuid4(), "Yes", ScriptedLlmClient(), TODAY)


async def test_a_reply_after_the_call_ended_is_refused_and_changes_nothing(
    session, school, student
):
    _, attempt_id = await call_in_progress(session, school, student)
    await handle_parent_reply(
        session, attempt_id, "Stop", ScriptedLlmClient(intent("opt_out")), TODAY
    )
    before = (await session.get(CallAttempt, attempt_id)).state_json

    with pytest.raises(TurnConflictError):
        await handle_parent_reply(session, attempt_id, "Hello?", ScriptedLlmClient(), TODAY)

    attempt = await session.get(CallAttempt, attempt_id)
    assert attempt.state_json == before
    assert attempt.turn_count == 1


class RacingLlm(ScriptedLlmClient):
    """While this turn waits for the model, another request applies a turn first."""

    def __init__(self, session, attempt_id, *responses):
        super().__init__(*responses)
        self._session = session
        self._attempt_id = attempt_id

    async def generate_json(self, **kwargs):
        await self._session.execute(
            update(CallAttempt)
            .where(CallAttempt.id == self._attempt_id)
            .values(turn_count=CallAttempt.turn_count + 1)
        )
        return await super().generate_json(**kwargs)


async def test_a_turn_that_lost_a_race_changes_nothing(session, school, student):
    _, attempt_id = await call_in_progress(session, school, student)
    initial = (await session.get(CallAttempt, attempt_id)).state_json
    llm = RacingLlm(session, attempt_id, intent("yes"))

    with pytest.raises(TurnConflictError):
        await handle_parent_reply(session, attempt_id, "Yes", llm, TODAY)

    attempt = await session.get(CallAttempt, attempt_id)
    await session.refresh(attempt)
    assert attempt.state_json == initial  # the loser wrote nothing
    assert attempt.turn_count == 1  # only the other request's increment
    assert attempt.status == CallAttemptStatus.IN_PROGRESS


async def test_a_call_with_no_primary_guardian_cannot_continue(session, school, student):
    _, attempt_id = await call_in_progress(session, school, student)
    await session.execute(delete(StudentGuardian))
    await session.flush()

    with pytest.raises(CallDataError):
        await handle_parent_reply(
            session, attempt_id, "Yes", ScriptedLlmClient(intent("yes")), TODAY
        )

    assert (await session.get(CallAttempt, attempt_id)).turn_count == 0
