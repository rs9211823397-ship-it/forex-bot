"""Rotating JSON-lines event logging with trace identifiers."""

from datetime import datetime, timezone
from enum import Enum
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping

from execution.models import require_utc_datetime


_SENSITIVE_KEY_PARTS = (
    "api_key",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


def _required_identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _safe_payload(value: Any, path: str = "payload") -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        require_utc_datetime(value, path)
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        result = {}
        for key, child in value.items():
            key_text = str(key)
            normalized = key_text.lower()
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                raise ValueError(
                    f"Sensitive field cannot be logged: {path}.{key_text}"
                )
            result[key_text] = _safe_payload(
                child,
                f"{path}.{key_text}",
            )
        return result
    if isinstance(value, (tuple, list)):
        return [
            _safe_payload(child, f"{path}[{index}]")
            for index, child in enumerate(value)
        ]
    raise TypeError(f"{path} is not JSON serializable")


class StructuredEventLogger:
    """Write one stable JSON object per event with size-based rotation."""

    def __init__(
        self,
        path: str | Path,
        *,
        max_bytes: int = 10_000_000,
        backup_count: int = 5,
        level: str = "INFO",
    ):
        if isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero")
        if isinstance(backup_count, bool) or backup_count <= 0:
            raise ValueError("backup_count must be greater than zero")
        resolved_level = str(level).strip().upper()
        if resolved_level not in _LOG_LEVELS:
            raise ValueError("level is not a valid logging level")

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(
            f"forex_bot.structured.{id(self)}"
        )
        self._logger.setLevel(resolved_level)
        self._logger.propagate = False
        self._handler = RotatingFileHandler(
            self.path,
            maxBytes=int(max_bytes),
            backupCount=int(backup_count),
            encoding="utf-8",
            delay=True,
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(self._handler)

    def log_event(
        self,
        event_type: str,
        message: str,
        *,
        correlation_id: str,
        account_id: str | None = None,
        order_id: str | None = None,
        event_time: datetime | None = None,
        payload: Mapping[str, Any] | None = None,
        level: str = "INFO",
    ) -> dict:
        """Write and return the exact event dictionary."""

        event_name = _required_identifier(event_type, "event_type")
        message_text = _required_identifier(message, "message")
        correlation = _required_identifier(
            correlation_id,
            "correlation_id",
        )
        if account_id is not None:
            account_id = _required_identifier(account_id, "account_id")
        if order_id is not None:
            order_id = _required_identifier(order_id, "order_id")

        timestamp = event_time or datetime.now(timezone.utc)
        require_utc_datetime(timestamp, "event_time")
        resolved_level = str(level).strip().upper()
        numeric_level = _LOG_LEVELS.get(resolved_level)
        if numeric_level is None:
            raise ValueError("level is not a valid logging level")

        event = {
            "account_id": account_id,
            "correlation_id": correlation,
            "event_time": timestamp.isoformat(),
            "event_type": event_name,
            "level": resolved_level,
            "message": message_text,
            "order_id": order_id,
            "payload": _safe_payload(payload or {}),
        }
        line = json.dumps(
            event,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._logger.log(numeric_level, line)
        self._handler.flush()
        return event

    def close(self):
        self._handler.flush()
        self._handler.close()
        self._logger.removeHandler(self._handler)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        del exc_type, exc_value, traceback
        self.close()
