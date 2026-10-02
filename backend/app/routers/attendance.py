"""Teacher-facing attendance endpoints."""

import logging
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance_service import (
    MarkResult,
    StudentNotFoundError,
    list_attendance_for_day,
    mark_attendance,
)
from app.dependencies import CurrentSchoolId, DbSession
from app.extraction import AbsenceReason
from app.models import AbsenceEventStatus, AttendanceStatus

logger = logging.getLogger(__name__)

router = APIRouter()


class MarkAttendanceRequest(BaseModel):
    status: AttendanceStatus


class AttendanceResponse(BaseModel):
    student_id: uuid.UUID
    attendance_date: date
    status: AttendanceStatus
    event_status: AbsenceEventStatus | None
    correction_notice_owed: bool


class DayEntryResponse(BaseModel):
    student_id: uuid.UUID
    student_name: str
    class_name: str
    section: str
    status: AttendanceStatus | None
    event_status: AbsenceEventStatus | None
    absence_reason: AbsenceReason | None
    expected_return_date: date | None
    needs_human_followup: bool | None


def _to_response(result: MarkResult) -> AttendanceResponse:
    event = result.event
    return AttendanceResponse(
        student_id=result.record.student_id,
        attendance_date=result.record.attendance_date,
        status=AttendanceStatus(result.record.status),
        event_status=AbsenceEventStatus(event.status) if event else None,
        correction_notice_owed=event.correction_notice_owed if event else False,
    )


async def _mark_and_commit(
    session: AsyncSession,
    school_id: uuid.UUID,
    student_id: uuid.UUID,
    day: date,
    status: AttendanceStatus,
) -> MarkResult:
    """Mark attendance and commit. Retry once if a concurrent duplicate beat us to the insert."""
    for attempt in (1, 2):
        try:
            result = await mark_attendance(session, school_id, student_id, day, status)
            await session.commit()
            return result
        except IntegrityError:
            await session.rollback()
            if attempt == 2:
                raise
            logger.warning("attendance_insert_race_retry")
    raise AssertionError("unreachable")  # pragma: no cover


@router.put("/students/{student_id}/attendance/{day}", response_model=AttendanceResponse)
async def put_attendance(
    student_id: uuid.UUID,
    day: date,
    body: MarkAttendanceRequest,
    school_id: CurrentSchoolId,
    session: DbSession,
) -> AttendanceResponse:
    """Set a student's attendance for a day. Repeating the same request changes nothing."""
    try:
        result = await _mark_and_commit(session, school_id, student_id, day, body.status)
    except StudentNotFoundError:
        # Same answer for "no such student" and "student of another school": no existence leak.
        raise HTTPException(status_code=404, detail="Student not found") from None
    logger.info(
        "attendance_marked",
        extra={
            "school_id": str(school_id),
            "student_id": str(student_id),
            "status": body.status.value,
        },
    )
    return _to_response(result)


@router.get("/attendance/{day}", response_model=list[DayEntryResponse])
async def get_attendance_for_day(
    day: date,
    school_id: CurrentSchoolId,
    session: DbSession,
) -> list[DayEntryResponse]:
    """List every student of the school with their status for the day (null if not marked)."""
    entries = await list_attendance_for_day(session, school_id, day)
    return [
        DayEntryResponse(
            student_id=e.student_id,
            student_name=e.student_name,
            class_name=e.class_name,
            section=e.section,
            status=AttendanceStatus(e.status) if e.status else None,
            event_status=AbsenceEventStatus(e.event_status) if e.event_status else None,
            absence_reason=AbsenceReason(e.absence_reason) if e.absence_reason else None,
            expected_return_date=e.expected_return_date,
            needs_human_followup=e.needs_human_followup,
        )
        for e in entries
    ]
