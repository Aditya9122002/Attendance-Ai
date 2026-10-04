"""Call service: run one phone call attempt for an absence event, turn by turn.

Purpose: start a call (claim the event, pick who to call, open an attempt, give the first
line) and handle each reply from the parent (understand it, decide the next line, save the
conversation state).
Input: an open AsyncSession plus an event id (start) or an attempt id and reply (turns).
Output: a CallStart, or a ReplyResult holding the next line to speak.
Dependencies: app.models, app.attendance_service, app.conversation, app.turn_analysis. The
caller owns the transaction (commit or rollback). The only network use is the injected
language model client.

Rules:
- Only a pending event can be started, and only once: the claim is one atomic UPDATE.
- Only the student's primary guardian is called. No primary guardian, or one who opted out,
  means a person must follow up: the event becomes needs_human and no attempt is created,
  because no call took place.
- After MAX_ATTEMPTS attempts the event also becomes needs_human instead of being called again.
- Only the student's first name is ever put in the conversation context.
- A turn is saved with a compare-and-set on `turn_count`. The model is called BEFORE that
  write and no write happens first, so a replayed or overlapping turn changes nothing and a
  crash mid-turn loses nothing. TurnConflictError means nothing was applied: roll back.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance_service import mark_needs_human, try_start_dialing
from app.conversation import (
    CallContext,
    ConversationState,
    Outcome,
    Step,
    decide,
    end_for_technical_problem,
    opening,
)
from app.llm.base import LlmClient
from app.models import (
    AbsenceEvent,
    AttendanceRecord,
    CallAttempt,
    CallAttemptStatus,
    Guardian,
    School,
    Student,
    StudentGuardian,
)
from app.turn_analysis import analyze_turn

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # calls per absence event before a person is asked to follow up
FALLBACK_STUDENT_NAME = "your child"  # spoken when a student record has no usable name


class StartResult(StrEnum):
    STARTED = "started"
    NOT_AVAILABLE = "not_available"  # unknown, cancelled, or already claimed by another caller
    NO_GUARDIAN = "no_guardian"  # event moved to needs_human
    TOO_MANY_ATTEMPTS = "too_many_attempts"  # event moved to needs_human


@dataclass(frozen=True)
class StartedCall:
    attempt_id: uuid.UUID
    event_id: uuid.UUID
    to_phone: str
    context: CallContext
    first_line: str


@dataclass(frozen=True)
class CallStart:
    result: StartResult
    call: StartedCall | None = None


class AttemptNotFoundError(Exception):
    """No call attempt has this id."""


class TurnConflictError(Exception):
    """The turn could not be applied (attempt over, or another turn got there first).

    Nothing was changed. The caller rolls back and decides what to tell the parent.
    """


class CallDataError(Exception):
    """The records needed to continue the call are missing (for example, no primary guardian)."""


@dataclass(frozen=True)
class ReplyResult:
    say: str  # the next line to speak
    ended: bool
    outcome: Outcome | None  # set once the call has ended


def _first_name(full_name: str) -> str:
    parts = full_name.split()
    return parts[0] if parts else FALLBACK_STUDENT_NAME


async def _student_and_school(session: AsyncSession, event_id: uuid.UUID) -> tuple[Student, School]:
    row = (
        await session.execute(
            select(Student, School)
            .select_from(AbsenceEvent)
            .join(AttendanceRecord, AttendanceRecord.id == AbsenceEvent.attendance_record_id)
            .join(Student, Student.id == AttendanceRecord.student_id)
            .join(School, School.id == Student.school_id)
            .where(AbsenceEvent.id == event_id)
        )
    ).one()
    return row[0], row[1]


async def _primary_guardian(session: AsyncSession, student_id: uuid.UUID) -> Guardian | None:
    return await session.scalar(
        select(Guardian)
        .join(StudentGuardian, StudentGuardian.guardian_id == Guardian.id)
        .where(StudentGuardian.student_id == student_id, StudentGuardian.is_primary.is_(True))
    )


def _context(school: School, student: Student, guardian: Guardian) -> CallContext:
    return CallContext(
        school_name=school.name,
        guardian_name=guardian.name,
        student_name=_first_name(student.name),
        language=guardian.language,
    )


async def start_call(
    session: AsyncSession, event_id: uuid.UUID, *, max_attempts: int = MAX_ATTEMPTS
) -> CallStart:
    """Claim the event and open the next call attempt. Does not commit."""
    if not await try_start_dialing(session, event_id):
        return CallStart(StartResult.NOT_AVAILABLE)

    student, school = await _student_and_school(session, event_id)

    attempts_so_far = await session.scalar(
        select(func.count())
        .select_from(CallAttempt)
        .where(CallAttempt.absence_event_id == event_id)
    )
    if attempts_so_far >= max_attempts:
        await mark_needs_human(session, event_id)
        logger.info("call_not_started", extra={"event_id": str(event_id), "why": "max_attempts"})
        return CallStart(StartResult.TOO_MANY_ATTEMPTS)

    guardian = await _primary_guardian(session, student.id)
    if guardian is None or guardian.opted_out:
        await mark_needs_human(session, event_id)
        logger.info("call_not_started", extra={"event_id": str(event_id), "why": "no_guardian"})
        return CallStart(StartResult.NO_GUARDIAN)

    attempt = CallAttempt(
        school_id=school.id,
        absence_event_id=event_id,
        attempt_number=attempts_so_far + 1,
        state_json=ConversationState().model_dump_json(),
    )
    session.add(attempt)
    await session.flush()

    context = _context(school, student, guardian)
    logger.info(
        "call_started",
        extra={"event_id": str(event_id), "attempt_number": attempt.attempt_number},
    )
    return CallStart(
        StartResult.STARTED,
        StartedCall(
            attempt_id=attempt.id,
            event_id=event_id,
            to_phone=guardian.phone,
            context=context,
            first_line=opening(context),
        ),
    )


async def handle_parent_reply(
    session: AsyncSession,
    attempt_id: uuid.UUID,
    reply: str,
    llm: LlmClient,
    today: date,
) -> ReplyResult:
    """Apply one parent reply to a call in progress and return the next line to speak.

    Does not commit. Raises AttemptNotFoundError, TurnConflictError or CallDataError; after
    any of them nothing has been changed.
    """
    attempt = await session.get(CallAttempt, attempt_id)
    if attempt is None:
        raise AttemptNotFoundError(str(attempt_id))
    if attempt.status != CallAttemptStatus.IN_PROGRESS:
        raise TurnConflictError("the call attempt is already finished")

    state = ConversationState.model_validate_json(attempt.state_json)
    if state.step == Step.ENDED:
        raise TurnConflictError("the conversation has already ended")
    expected_turn = attempt.turn_count

    student, school = await _student_and_school(session, attempt.absence_event_id)
    guardian = await _primary_guardian(session, student.id)
    if guardian is None:
        raise CallDataError("the student has no primary guardian")
    ctx = _context(school, student, guardian)

    # Slow part first (seconds), before any write, so no transaction work is held up by it.
    turn = await analyze_turn(llm, state.step, reply, today)
    if turn.analysis is None:
        result = end_for_technical_problem(state, ctx)
    else:
        result = decide(state, turn.analysis, ctx)
    new_state = result.state

    values: dict[str, object] = {
        "state_json": new_state.model_dump_json(),
        "turn_count": expected_turn + 1,
    }
    if new_state.step == Step.ENDED:
        values |= {
            "status": CallAttemptStatus.FINISHED.value,
            "outcome": new_state.outcome.value if new_state.outcome else None,
            "ended_at": datetime.now(UTC),
        }
    saved = await session.execute(
        update(CallAttempt)
        .where(
            CallAttempt.id == attempt_id,
            CallAttempt.turn_count == expected_turn,
            CallAttempt.status == CallAttemptStatus.IN_PROGRESS.value,
        )
        .values(**values)
    )
    if saved.rowcount != 1:
        raise TurnConflictError("another turn was applied first")
    await session.refresh(attempt)

    logger.info(
        "call_turn_applied",
        extra={
            "attempt_id": str(attempt_id),
            "turn": expected_turn + 1,
            "step": new_state.step.value,
        },
    )
    return ReplyResult(say=result.say, ended=result.ended, outcome=new_state.outcome)
