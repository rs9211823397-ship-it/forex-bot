"""Strict local economic-calendar adapter with no external dependency."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from risk.portfolio import as_utc
from risk.protection import NewsEvent


class NewsCalendarError(ValueError):
    """Raised when the configured calendar cannot be trusted."""


class JsonNewsEventProvider:
    """Load immutable scheduled events from a validated local JSON file.

    The file may contain either a top-level list or ``{"events": [...]}``.
    It is parsed once at construction so a running decision cycle cannot see a
    calendar file change halfway through an assessment.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._events = self._load()

    def _load(self) -> tuple[NewsEvent, ...]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise NewsCalendarError(
                f"News calendar file not found: {self.path}"
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise NewsCalendarError(
                f"News calendar file is unreadable or invalid: {self.path}"
            ) from exc

        rows = payload.get("events") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise NewsCalendarError(
                "News calendar must be a list or an object with an events list"
            )

        events = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise NewsCalendarError(
                    f"News event {index} must be a JSON object"
                )
            try:
                event_time = datetime.fromisoformat(
                    str(row["event_time"]).replace("Z", "+00:00")
                )
                currencies = row.get("currencies", [])
                if not isinstance(currencies, list):
                    raise TypeError("currencies must be a list")
                events.append(
                    NewsEvent(
                        event_time=event_time,
                        impact=str(row["impact"]),
                        currencies=tuple(str(item) for item in currencies),
                        name=str(row.get("name", "")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise NewsCalendarError(
                    f"News event {index} is invalid: {exc}"
                ) from exc
        return tuple(sorted(events, key=lambda item: item.event_time))

    @property
    def events(self) -> tuple[NewsEvent, ...]:
        return self._events

    def events_between(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[NewsEvent, ...]:
        start = as_utc(start_time, "start_time")
        end = as_utc(end_time, "end_time")
        if end < start:
            raise NewsCalendarError("end_time cannot precede start_time")
        return tuple(
            event
            for event in self._events
            if start <= event.event_time <= end
        )


__all__ = ["JsonNewsEventProvider", "NewsCalendarError"]
