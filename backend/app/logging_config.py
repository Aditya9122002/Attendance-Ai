"""Logging setup: JSON lines in production, readable text in development."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Attributes every LogRecord has. Anything else was passed via `extra=` and is context.
_RESERVED_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message"}

CONSOLE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


class JsonFormatter(logging.Formatter):
    """Format each log record as one JSON object per line.

    Purpose: make logs machine-searchable.
    Input: a logging.LogRecord (extra fields become top-level keys).
    Output: a single-line JSON string.
    Dependencies: standard library only.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str, json_output: bool) -> None:
    """Configure the root logger once, replacing any existing handlers."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else logging.Formatter(CONSOLE_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
