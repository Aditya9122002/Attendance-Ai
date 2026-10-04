from pathlib import Path

from alembic import command
from alembic.config import Config

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def test_migrations_apply_and_match_models(tmp_path):
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{tmp_path.as_posix()}/m.db")
    command.upgrade(config, "head")
    command.check(config)


def test_migrated_database_rejects_an_unknown_reason(tmp_path):
    """Alembic does not autogenerate check constraints, so prove the migration really has it."""
    import sqlalchemy as sa
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from app.models import AbsenceEvent, AttendanceRecord, School, Student

    db = tmp_path / "check.db"
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db.as_posix()}")
    command.upgrade(config, "head")

    engine = sa.create_engine(f"sqlite:///{db.as_posix()}")
    with Session(engine) as session:
        school = School(name="S")
        session.add(school)
        session.flush()
        student = Student(school_id=school.id, name="A", class_name="5", section="A")
        session.add(student)
        session.flush()
        record = AttendanceRecord(
            school_id=school.id,
            student_id=student.id,
            attendance_date=sa.func.date("2026-10-01"),
            status="absent",
        )
        session.add(record)
        session.flush()
        session.add(
            AbsenceEvent(school_id=school.id, attendance_record_id=record.id, reason="aliens")
        )
        try:
            session.flush()
        except IntegrityError:
            return
    raise AssertionError("the migrated database accepted an unknown reason")


def _migrated_engine(tmp_path, name: str):
    import sqlalchemy as sa

    db = tmp_path / name
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db.as_posix()}")
    command.upgrade(config, "head")
    return config, sa.create_engine(f"sqlite:///{db.as_posix()}")


def _seed_event(session, status: str):
    import datetime as dt

    from app.models import AbsenceEvent, AttendanceRecord, School, Student

    school = School(name="S")
    session.add(school)
    session.flush()
    student = Student(school_id=school.id, name="A", class_name="5", section="A")
    session.add(student)
    session.flush()
    record = AttendanceRecord(
        school_id=school.id,
        student_id=student.id,
        attendance_date=dt.date(2026, 10, 1),
        status="absent",
    )
    session.add(record)
    session.flush()
    event = AbsenceEvent(school_id=school.id, attendance_record_id=record.id, status=status)
    session.add(event)
    session.flush()
    return event


def test_migrated_database_accepts_needs_human_but_not_other_statuses(tmp_path):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    _, engine = _migrated_engine(tmp_path, "status.db")
    with Session(engine) as session:
        event = _seed_event(session, "needs_human")
        assert event.status == "needs_human"
        event.status = "bogus"
        try:
            session.flush()
        except IntegrityError:
            return
    raise AssertionError("the migrated database accepted an unknown event status")


def test_downgrade_turns_needs_human_events_into_failed_and_upgrade_works_again(tmp_path):
    import sqlalchemy as sa
    from sqlalchemy.orm import Session

    config, engine = _migrated_engine(tmp_path, "down.db")
    with Session(engine) as session:
        _seed_event(session, "needs_human")
        session.commit()
    engine.dispose()

    command.downgrade(config, "-1")
    _, engine = config, sa.create_engine(engine.url)
    with engine.connect() as conn:
        statuses = conn.execute(sa.text("SELECT status FROM absence_events")).scalars().all()
        tables = sa.inspect(conn).get_table_names()
    assert statuses == ["failed"]
    assert "call_attempts" not in tables
    engine.dispose()

    command.upgrade(config, "head")
    command.check(config)
