"""Call service: start one phone call attempt for an absence event.

Purpose: claim a pending absence event, find who to call, open a call attempt and hand back
the first line to speak.
Input: an open AsyncSession and the id of an absence event.
Output: a CallStart saying what happened and, when a call can go ahead, the StartedCall
(attempt id, number to dial, conversation context, opening line).
Dependencies: app.models, app.attendance_service, app.conversation. The caller owns the
transaction (commit or rollback). No network and no language model here.

Rules:
- Only a pending event can be started, and only once: the claim is one atomic UPDATE.
- Only the student's primary guardian is called. No primary guardian, or one who opted out,
  means a person must follow up: the event becomes needs_human and no attempt is created,
  because no call took place.
- After MAX_ATTEMPTS attempts the event also becomes needs_human instead of being called again.
- Only the student's first name is ever put in the conversation context.
"""

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance_service import mark_needs_human, try_start_dialing
from app.conversation import CallContext, ConversationState, opening
from app.models import (
    AbsenceEvent,
    AttendanceRecord,
    CallAttempt,
    Guardian,
    School,
    Student,
    StudentGuardian,
)

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


def _first_name(full_name: str) -> str:
    parts = full_name.split()
    return parts[0] if parts else FALLBACK_STUDENT_NAME


async def start_call(
    session: AsyncSession, event_id: uuid.UUID, *, max_attempts: int = MAX_ATTEMPTS
) -> CallStart:
    """Claim the event and open the next call attempt. Does not commit."""
    if not await try_start_dialing(session, event_id):
        return CallStart(StartResult.NOT_AVAILABLE)

    student, school = (
        await session.execute(
            select(Student, School)
            .select_from(AbsenceEvent)
            .join(AttendanceRecord, AttendanceRecord.id == AbsenceEvent.attendance_record_id)
            .join(Student, Student.id == AttendanceRecord.student_id)
            .join(School, School.id == Student.school_id)
            .where(AbsenceEvent.id == event_id)
        )
    ).one()

    attempts_so_far = await session.scalar(
        select(func.count())
        .select_from(CallAttempt)
        .where(CallAttempt.absence_event_id == event_id)
    )
    if attempts_so_far >= max_attempts:
        await mark_needs_human(session, event_id)
        logger.info("call_not_started", extra={"event_id": str(event_id), "why": "max_attempts"})
        return CallStart(StartResult.TOO_MANY_ATTEMPTS)

    guardian = await session.scalar(
        select(Guardian)
        .join(StudentGuardian, StudentGuardian.guardian_id == Guardian.id)
        .where(StudentGuardian.student_id == student.id, StudentGuardian.is_primary.is_(True))
    )
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

    context = CallContext(
        school_name=school.name,
        guardian_name=guardian.name,
        student_name=_first_name(student.name),
        language=guardian.language,
    )
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
