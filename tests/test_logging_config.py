import json
import logging
import sys
from collections.abc import Iterator

import pytest

from app.logging_config import JsonFormatter, configure_logging


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    """configure_logging mutates global state, so put it back after each test."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _record(msg: str = "hello", exc_info=None) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, msg, (), exc_info)


def test_json_formatter_includes_core_fields_and_extras() -> None:
    record = _record("call_started")
    record.student_id = 42

    data = json.loads(JsonFormatter().format(record))

    assert data["message"] == "call_started"
    assert data["level"] == "INFO"
    assert data["logger"] == "test"
    assert data["student_id"] == 42


def test_json_formatter_includes_exception_details() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = _record(exc_info=sys.exc_info())

    data = json.loads(JsonFormatter().format(record))

    assert "ValueError: boom" in data["exception"]


def test_json_formatter_survives_unserializable_extras() -> None:
    record = _record()
    record.payload = object()

    assert json.loads(JsonFormatter().format(record))["message"] == "hello"


def test_configure_logging_sets_level_and_single_handler() -> None:
    configure_logging("WARNING", json_output=True)
    configure_logging("WARNING", json_output=True)  # calling twice must not duplicate handlers

    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert len(root.handlers) == 1
