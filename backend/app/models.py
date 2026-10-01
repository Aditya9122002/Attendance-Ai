"""ORM models: schools, students, guardians and the links between them."""

import uuid
from datetime import UTC, datetime

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


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
