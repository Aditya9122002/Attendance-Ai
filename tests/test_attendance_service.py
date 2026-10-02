import uuid
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.attendance_service import StudentNotFoundError, mark_attendance, try_start_dialing
from app.models import (
    AbsenceEvent,
    AbsenceEventStatus,
    AttendanceRecord,
    AttendanceStatus,
    School,
)

DAY = date(2026, 10, 1)


async def count_events(session) -> int:
    return await session.scalar(select(func.count()).select_from(AbsenceEvent))


async def test_marking_absent_creates_one_pending_event(session, school, student):
    result = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    assert result.record.status == "absent"
    assert result.event is not None
    assert result.event.status == AbsenceEventStatus.PENDING


async def test_marking_present_creates_no_event(session, school, student):
    result = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.PRESENT)
    assert result.event is None
    assert await count_events(session) == 0


async def test_marking_absent_twice_is_idempotent(session, school, student):
    first = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    second = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    assert second.record.id == first.record.id
    assert second.event.id == first.event.id
    assert await count_events(session) == 1


async def test_correction_before_call_cancels_the_event(session, school, student):
    await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    result = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.PRESENT)
    assert result.record.status == "present"
    assert result.event.status == AbsenceEventStatus.CANCELLED
    assert result.event.correction_notice_owed is False


async def test_correction_after_call_started_keeps_event_and_flags_notice(session, school, student):
    first = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    assert await try_start_dialing(session, first.event.id) is True
    result = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.PRESENT)
    assert result.event.status == AbsenceEventStatus.DIALING
    assert result.event.correction_notice_owed is True


async def test_no_notice_flagged_when_school_opts_out(session, school, student):
    school.notify_parent_on_correction = False
    first = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    await try_start_dialing(session, first.event.id)
    result = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.PRESENT)
    assert result.event.status == AbsenceEventStatus.DIALING
    assert result.event.correction_notice_owed is False


async def test_marking_absent_again_reopens_the_cancelled_event(session, school, student):
    first = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.PRESENT)
    result = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    assert result.event.id == first.event.id
    assert result.event.status == AbsenceEventStatus.PENDING
    assert await count_events(session) == 1


async def test_marking_absent_again_clears_a_flagged_notice(session, school, student):
    first = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    await try_start_dialing(session, first.event.id)
    await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.PRESENT)
    result = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    assert result.event.status == AbsenceEventStatus.DIALING
    assert result.event.correction_notice_owed is False
    assert await count_events(session) == 1


async def test_dialer_cannot_claim_a_cancelled_event(session, school, student):
    first = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.PRESENT)
    assert await try_start_dialing(session, first.event.id) is False


async def test_an_event_can_only_be_claimed_once(session, school, student):
    first = await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.ABSENT)
    assert await try_start_dialing(session, first.event.id) is True
    assert await try_start_dialing(session, first.event.id) is False


async def test_unknown_student_is_rejected(session, school):
    with pytest.raises(StudentNotFoundError):
        await mark_attendance(session, school.id, uuid.uuid4(), DAY, AttendanceStatus.ABSENT)


async def test_student_of_another_school_is_rejected(session, school, student):
    other = School(name="Other School")
    session.add(other)
    await session.flush()
    with pytest.raises(StudentNotFoundError):
        await mark_attendance(session, other.id, student.id, DAY, AttendanceStatus.ABSENT)


async def test_database_rejects_a_second_record_for_the_same_day(session, school, student):
    await mark_attendance(session, school.id, student.id, DAY, AttendanceStatus.PRESENT)
    session.add(
        AttendanceRecord(
            school_id=school.id,
            student_id=student.id,
            attendance_date=DAY,
            status=AttendanceStatus.ABSENT,
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_database_rejects_an_unknown_status(session, school, student):
    session.add(
        AttendanceRecord(
            school_id=school.id, student_id=student.id, attendance_date=DAY, status="maybe"
        )
    )
    with pytest.raises(IntegrityError):
        await session.flush()
