"""ORM models: schools, students, guardians, attendance and absence events."""

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AttendanceStatus(StrEnum):
    """Whether a student attended on a given day."""

    PRESENT = "present"
    ABSENT = "absent"


class AbsenceEventStatus(StrEnum):
    """Lifecycle of the follow-up call for an absence."""

    PENDING = "pending"
    CANCELLED = "cancelled"
    DIALING = "dialing"
    COMPLETED = "completed"
    FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _in_values(column: str, enum_class: type[StrEnum]) -> str:
    """Build a SQL `column IN (...)` check from the enum's values."""
    values = ", ".join(f"'{member.value}'" for member in enum_class)
    return f"{column} IN ({values})"


class School(Base):
    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    notify_parent_on_correction: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Student(Base):
    __tablename__ = "students"
    # Lets other tables reference (school_id, id) so a link can never cross schools.
    __table_args__ = (UniqueConstraint("school_id", "id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    class_name: Mapped[str] = mapped_column(String(20))
    section: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Guardian(Base):
    __tablename__ = "guardians"
    __table_args__ = (
        UniqueConstraint("school_id", "id"),
        CheckConstraint("substr(phone, 1, 1) = '+'", name="phone_e164_prefix"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8), default="en")
    opted_out: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class StudentGuardian(Base):
    __tablename__ = "student_guardians"
    __table_args__ = (
        ForeignKeyConstraint(["school_id", "student_id"], ["students.school_id", "students.id"]),
        ForeignKeyConstraint(["school_id", "guardian_id"], ["guardians.school_id", "guardians.id"]),
        # At most one primary guardian per student.
        Index(
            "uq_student_guardians_one_primary",
            "student_id",
            unique=True,
            sqlite_where=text("is_primary"),
            postgresql_where=text("is_primary"),
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    guardian_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    school_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("schools.id"), index=True)
    is_primary: Mapped[bool] = mapped_column(default=False)


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        # One record per student per day. This constraint is what makes marking idempotent.
        UniqueConstraint(
            "school_id",
            "student_id",
            "attendance_date",
            name="uq_attendance_records_school_student_date",
        ),
        # Lets absence_events reference (school_id, id).
        UniqueConstraint("school_id", "id", name="uq_attendance_records_school_id_id"),
        ForeignKeyConstraint(["school_id", "student_id"], ["students.school_id", "students.id"]),
        CheckConstraint(_in_values("status", AttendanceStatus), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID]
    student_id: Mapped[uuid.UUID]
    attendance_date: Mapped[date]
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AbsenceEvent(Base):
    __tablename__ = "absence_events"
    __table_args__ = (
        # At most one event per attendance record, ever.
        UniqueConstraint("attendance_record_id"),
        ForeignKeyConstraint(
            ["school_id", "attendance_record_id"],
            ["attendance_records.school_id", "attendance_records.id"],
        ),
        CheckConstraint(_in_values("status", AbsenceEventStatus), name="status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    school_id: Mapped[uuid.UUID]
    attendance_record_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(
        String(16), default=AbsenceEventStatus.PENDING.value, index=True
    )
    correction_notice_owed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
