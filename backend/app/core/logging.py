from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import get_request_id

APPLICATION_LOGGER_NAME = "scms"
_HANDLER_MARKER = "_scms_json_handler"
_STRUCTURED_FIELDS = ("method", "path", "status", "duration_ms")


class JsonFormatter(logging.Formatter):
    """Format application records as compact, one-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", None) or record.getMessage()
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "event": event,
        }

        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id

        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_logging() -> logging.Logger:
    """Configure the SCMS logger without altering Uvicorn's logging setup."""
    logger = logging.getLogger(APPLICATION_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        setattr(handler, _HANDLER_MARKER, True)
        logger.addHandler(handler)

    return logger
