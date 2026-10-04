"""Attendance service: record attendance and drive the absence event lifecycle.

Purpose: mark a student present or absent for a day, creating, cancelling or reopening
the absence event according to the school's rules.
Input: an open AsyncSession, the school and student ids, the day and the new status.
Output: a MarkResult holding the attendance record and its absence event (if any).
Dependencies: app.models only. The caller owns the transaction (commit or rollback).

Rules:
- One attendance record per student per day, and one absence event per record.
- Marking absent creates a pending event in the same transaction as the record.
- A correction to present cancels the event only while it is still pending.
- If the call already started it proceeds, and a correction notice is flagged when the
  school wants parents told about corrections.
- Marking absent again reopens a cancelled event instead of creating a second one.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.extraction import Extraction
from app.models import (
    AbsenceEvent,
    AbsenceEventStatus,
    AttendanceRecord,
    AttendanceStatus,
    School,
    Student,
)


class StudentNotFoundError(Exception):
    """The student does not exist in this school."""


@dataclass(frozen=True)
class MarkResult:
    record: AttendanceRecord
    event: AbsenceEvent | None


async def mark_attendance(
    session: AsyncSession,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    day: date,
    status: AttendanceStatus,
) -> MarkResult:
    """Mark attendance for one student and day. Safe to call repeatedly with the same input.

    A concurrent duplicate request loses at the database unique constraint and raises
    IntegrityError; the API layer retries once, and the retry finds the existing record.
    """
    student_exists = await session.scalar(
        select(Student.id).where(Student.id == student_id, Student.school_id == school_id)
    )
    if student_exists is None:
        raise StudentNotFoundError(str(student_id))

    record = await session.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.school_id == school_id,
            AttendanceRecord.student_id == student_id,
            AttendanceRecord.attendance_date == day,
        )
    )
    if record is None:
        return await _create_record(session, school_id, student_id, day, status)

    event = await _get_event(session, record.id)
    if record.status == status:
        return MarkResult(record, event)

    record.status = status
    if status == AttendanceStatus.ABSENT:
        event = await _handle_marked_absent(session, school_id, record, event)
    else:
        event = await _handle_corrected_to_present(session, school_id, event)
    await session.flush()
    return MarkResult(record, event)


async def try_start_dialing(session: AsyncSession, event_id: uuid.UUID) -> bool:
    """Claim a pending event for dialing. Returns False if it was cancelled or already claimed."""
    return await _transition(
        session, event_id, source=AbsenceEventStatus.PENDING, target=AbsenceEventStatus.DIALING
    )


async def record_extraction(
    session: AsyncSession, event_id: uuid.UUID, extraction: Extraction, prompt_version: str
) -> bool:
    """Save what the call learned. Only allowed while the call is in progress (dialing).

    Returns False if the event is not dialing, so a late result can never change an event
    that was already completed, failed or cancelled. Calling it again during the same call
    overwrites the earlier values (a parent may correct themselves).
    """
    result = await session.execute(
        update(AbsenceEvent)
        .where(AbsenceEvent.id == event_id, AbsenceEvent.status == AbsenceEventStatus.DIALING)
        .values(
            reason=extraction.reason.value,
            expected_return_date=extraction.expected_return_date,
            needs_human_followup=extraction.needs_human_followup,
            extraction_prompt_version=prompt_version,
            extracted_at=datetime.now(UTC),
        )
        .returning(AbsenceEvent.id)
    )
    return result.scalar_one_or_none() is not None


async def complete_event(session: AsyncSession, event_id: uuid.UUID) -> bool:
    """The call finished and its result was saved. Only a dialing event can complete."""
    return await _transition(
        session, event_id, source=AbsenceEventStatus.DIALING, target=AbsenceEventStatus.COMPLETED
    )


async def release_for_retry(session: AsyncSession, event_id: uuid.UUID) -> bool:
    """Put an unfinished call back in the queue. Only a dialing event can be released."""
    return await _transition(
        session, event_id, source=AbsenceEventStatus.DIALING, target=AbsenceEventStatus.PENDING
    )


async def mark_needs_human(session: AsyncSession, event_id: uuid.UUID) -> bool:
    """A person must follow up. Final. Only a dialing event can move here."""
    return await _transition(
        session,
        event_id,
        source=AbsenceEventStatus.DIALING,
        target=AbsenceEventStatus.NEEDS_HUMAN,
    )


async def fail_event(session: AsyncSession, event_id: uuid.UUID) -> bool:
    """The call could not be completed. Only a dialing event can fail."""
    return await _transition(
        session, event_id, source=AbsenceEventStatus.DIALING, target=AbsenceEventStatus.FAILED
    )


async def _create_record(
    session: AsyncSession,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    day: date,
    status: AttendanceStatus,
) -> MarkResult:
    record = AttendanceRecord(
        school_id=school_id, student_id=student_id, attendance_date=day, status=status
    )
    session.add(record)
    await session.flush()
    event = (
        await _create_event(session, school_id, record.id)
        if status == AttendanceStatus.ABSENT
        else None
    )
    return MarkResult(record, event)


async def _create_event(
    session: AsyncSession, school_id: uuid.UUID, record_id: uuid.UUID
) -> AbsenceEvent:
    event = AbsenceEvent(school_id=school_id, attendance_record_id=record_id)
    session.add(event)
    await session.flush()
    return event


async def _get_event(session: AsyncSession, record_id: uuid.UUID) -> AbsenceEvent | None:
    return await session.scalar(
        select(AbsenceEvent).where(AbsenceEvent.attendance_record_id == record_id)
    )


async def _handle_marked_absent(
    session: AsyncSession,
    school_id: uuid.UUID,
    record: AttendanceRecord,
    event: AbsenceEvent | None,
) -> AbsenceEvent:
    """Present -> absent: create the event, or reopen a cancelled one and clear any notice."""
    if event is None:
        return await _create_event(session, school_id, record.id)
    await _transition(
        session, event.id, source=AbsenceEventStatus.CANCELLED, target=AbsenceEventStatus.PENDING
    )
    await session.execute(
        update(AbsenceEvent).where(AbsenceEvent.id == event.id).values(correction_notice_owed=False)
    )
    await session.refresh(event)
    return event


async def _handle_corrected_to_present(
    session: AsyncSession, school_id: uuid.UUID, event: AbsenceEvent | None
) -> AbsenceEvent | None:
    """Absent -> present: cancel while pending, otherwise flag a notice if the school wants one."""
    if event is None:
        return None
    cancelled = await _transition(
        session, event.id, source=AbsenceEventStatus.PENDING, target=AbsenceEventStatus.CANCELLED
    )
    if not cancelled and await _school_notifies_on_correction(session, school_id):
        await session.execute(
            update(AbsenceEvent)
            .where(AbsenceEvent.id == event.id)
            .values(correction_notice_owed=True)
        )
    await session.refresh(event)
    return event


async def _school_notifies_on_correction(session: AsyncSession, school_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(School.notify_parent_on_correction).where(School.id == school_id)
    )
    return result.scalar_one()


async def _transition(
    session: AsyncSession,
    event_id: uuid.UUID,
    *,
    source: AbsenceEventStatus,
    target: AbsenceEventStatus,
) -> bool:
    """Atomically move an event from source to target.

    One UPDATE with the expected current status in its WHERE clause. If another
    transaction changed the status first, no row matches and we return False.
    """
    result = await session.execute(
        update(AbsenceEvent)
        .where(AbsenceEvent.id == event_id, AbsenceEvent.status == source)
        .values(status=target)
        .returning(AbsenceEvent.id)
    )
    return result.scalar_one_or_none() is not None


@dataclass(frozen=True)
class DayEntry:
    student_id: uuid.UUID
    student_name: str
    class_name: str
    section: str
    status: str | None
    event_status: str | None
    absence_reason: str | None
    expected_return_date: date | None
    needs_human_followup: bool | None


async def list_attendance_for_day(
    session: AsyncSession, school_id: uuid.UUID, day: date
) -> list[DayEntry]:
    """Every student of the school with their status and event status for the day."""
    rows = await session.execute(
        select(
            Student.id,
            Student.name,
            Student.class_name,
            Student.section,
            AttendanceRecord.status,
            AbsenceEvent.status,
            AbsenceEvent.reason,
            AbsenceEvent.expected_return_date,
            AbsenceEvent.needs_human_followup,
        )
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.school_id == Student.school_id)
            & (AttendanceRecord.student_id == Student.id)
            & (AttendanceRecord.attendance_date == day),
        )
        .outerjoin(AbsenceEvent, AbsenceEvent.attendance_record_id == AttendanceRecord.id)
        .where(Student.school_id == school_id)
        .order_by(Student.class_name, Student.section, Student.name)
    )
    return [DayEntry(*row) for row in rows]
