"""Run one whole phone call in the terminal, with a person typing the parent's replies.

Purpose: let a developer play the parent (and the phone layer) to try the call flow end to
end before Twilio exists.
Input: a language model client, a way to read a reply, a way to show a line, today's date.
Output: a SimulationReport describing what the database holds when the call is over.
Dependencies: app.call_service, app.attendance_service, app.models. Uses a throwaway
in-memory database with made-up data, so nothing real is read or kept.

Privacy: the transcript is shown on screen only. It is not stored anywhere, the same as in
the real call flow.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.attendance_service import mark_attendance
from app.call_service import (
    CallDataError,
    StartResult,
    TurnConflictError,
    handle_parent_reply,
    start_call,
)
from app.conversation import Outcome
from app.database import Base, create_engine, create_session_factory
from app.llm.base import LlmClient
from app.models import (
    AbsenceEvent,
    AttendanceStatus,
    CallAttempt,
    Guardian,
    School,
    Student,
    StudentGuardian,
)

DEMO_PHONE = "+919800000001"  # made up


@dataclass(frozen=True)
class SimulationReport:
    start_result: StartResult
    turns: int
    dropped: bool  # the "parent" hung up (input ended) before the call finished
    error: str | None
    outcome: Outcome | None
    event_status: str
    reason: str | None
    expected_return_date: date | None
    needs_human_followup: bool
    prompt_version: str | None
    attempt_number: int | None
    guardian_opted_out: bool


async def run_simulation(
    llm: LlmClient,
    read_reply: Callable[[], str | None],
    say: Callable[[str], None],
    today: date,
) -> SimulationReport:
    """Play one call. `read_reply` returns None when the parent hangs up."""
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with create_session_factory(engine)() as session:
            school = School(name="Sunrise School")
            session.add(school)
            await session.flush()
            student = Student(school_id=school.id, name="Asha Patil", class_name="5", section="A")
            guardian = Guardian(
                school_id=school.id, name="Mr. Patil", phone=DEMO_PHONE, language="en"
            )
            session.add_all([student, guardian])
            await session.flush()
            session.add(
                StudentGuardian(
                    school_id=school.id,
                    student_id=student.id,
                    guardian_id=guardian.id,
                    is_primary=True,
                )
            )
            marked = await mark_attendance(
                session, school.id, student.id, today, AttendanceStatus.ABSENT
            )
            event_id = marked.event.id
            await session.commit()

            started = await start_call(session, event_id)
            await session.commit()

            turns, dropped, error, outcome = 0, False, None, None
            if started.call is not None:
                say(started.call.first_line)
                while True:
                    reply = read_reply()
                    if reply is None:
                        dropped = True
                        break
                    try:
                        result = await handle_parent_reply(
                            session, started.call.attempt_id, reply, llm, today
                        )
                    except (TurnConflictError, CallDataError) as exc:
                        await session.rollback()
                        error = f"{type(exc).__name__}: {exc}"
                        break
                    await session.commit()
                    turns += 1
                    say(result.say)
                    if result.ended:
                        outcome = result.outcome
                        break

            event = await session.get(AbsenceEvent, event_id)
            await session.refresh(event)
            await session.refresh(guardian)
            attempt_number = None
            if started.call is not None:
                attempt = await session.get(CallAttempt, started.call.attempt_id)
                attempt_number = attempt.attempt_number
            return SimulationReport(
                start_result=started.result,
                turns=turns,
                dropped=dropped,
                error=error,
                outcome=outcome,
                event_status=event.status,
                reason=event.reason,
                expected_return_date=event.expected_return_date,
                needs_human_followup=event.needs_human_followup,
                prompt_version=event.extraction_prompt_version,
                attempt_number=attempt_number,
                guardian_opted_out=guardian.opted_out,
            )
    finally:
        await engine.dispose()
