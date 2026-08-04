"""Validated economic-calendar providers used by the production risk layer."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from risk.portfolio import as_utc
from risk.protection import NewsEvent


DEFAULT_FOREX_FACTORY_URL = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
)


class NewsCalendarError(ValueError):
    """Raised when the configured calendar cannot be trusted."""


def _parse_event_time(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NewsCalendarError(f"Invalid event time: {value!r}") from exc
    return as_utc(parsed, "event_time")


def _normalise_impact(value: object) -> str | None:
    impact = str(value).strip().upper()
    aliases = {
        "HIGH": "HIGH",
        "RED": "HIGH",
        "MEDIUM": "MEDIUM",
        "MED": "MEDIUM",
        "ORANGE": "MEDIUM",
        "LOW": "LOW",
        "YELLOW": "LOW",
    }
    return aliases.get(impact)


def _parse_rows(payload: object) -> tuple[NewsEvent, ...]:
    rows = payload.get("events") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise NewsCalendarError(
            "News calendar must be a list or an object with an events list"
        )

    events: list[NewsEvent] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise NewsCalendarError(f"News event {index} must be a JSON object")

        # Native AAQTS format.
        if "event_time" in row:
            try:
                currencies = row.get("currencies", [])
                if not isinstance(currencies, list):
                    raise TypeError("currencies must be a list")
                events.append(
                    NewsEvent(
                        event_time=_parse_event_time(row["event_time"]),
                        impact=str(row["impact"]),
                        currencies=tuple(str(item) for item in currencies),
                        name=str(row.get("name", "")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise NewsCalendarError(
                    f"News event {index} is invalid: {exc}"
                ) from exc
            continue

        # Forex Factory weekly JSON export format:
        # title, country, date, impact, forecast, previous.
        if "date" in row and ("country" in row or "currency" in row):
            impact = _normalise_impact(row.get("impact"))
            if impact is None:
                # Holidays/non-economic rows are intentionally ignored; the
                # risk filter only consumes LOW/MEDIUM/HIGH economic events.
                continue
            currency = str(row.get("country") or row.get("currency") or "").strip().upper()
            if not currency:
                raise NewsCalendarError(
                    f"News event {index} has no currency/country code"
                )
            events.append(
                NewsEvent(
                    event_time=_parse_event_time(row["date"]),
                    impact=impact,
                    currencies=(currency,),
                    name=str(row.get("title") or row.get("name") or ""),
                )
            )
            continue

        raise NewsCalendarError(
            f"News event {index} does not match a supported calendar schema"
        )

    return tuple(sorted(events, key=lambda item: item.event_time))


class JsonNewsEventProvider:
    """Load scheduled events from a validated local JSON file."""

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
        return _parse_rows(payload)

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
            event for event in self._events if start <= event.event_time <= end
        )


class RefreshingNewsEventProvider:
    """Refresh a remote JSON calendar and fail closed once its cache is stale.

    A successful response is atomically cached on disk. Network failures may
    temporarily fall back to the cache, but only while that cache is younger
    than ``max_stale``. Once stale, ``events_between`` raises so the portfolio
    risk manager can block new entries instead of silently trading blind.
    """

    def __init__(
        self,
        url: str = DEFAULT_FOREX_FACTORY_URL,
        *,
        cache_path: str | Path = "runtime/news_calendar_cache.json",
        refresh_interval: timedelta = timedelta(minutes=30),
        max_stale: timedelta = timedelta(hours=6),
        timeout_seconds: float = 10.0,
        opener: Callable[..., object] | None = None,
    ) -> None:
        self.url = str(url).strip()
        if not self.url.startswith(("https://", "http://")):
            raise NewsCalendarError("News calendar URL must be HTTP(S)")
        if refresh_interval <= timedelta(0):
            raise NewsCalendarError("refresh_interval must be positive")
        if max_stale <= timedelta(0):
            raise NewsCalendarError("max_stale must be positive")
        if timeout_seconds <= 0:
            raise NewsCalendarError("timeout_seconds must be positive")
        self.cache_path = Path(cache_path).expanduser().resolve()
        self.refresh_interval = refresh_interval
        self.max_stale = max_stale
        self.timeout_seconds = float(timeout_seconds)
        self._opener = opener or urllib.request.urlopen
        self._events: tuple[NewsEvent, ...] = ()
        self._last_success: datetime | None = None
        self._last_attempt: datetime | None = None
        self._load_cache_if_available()

    @property
    def events(self) -> tuple[NewsEvent, ...]:
        self._ensure_fresh(datetime.now(timezone.utc))
        return self._events

    @property
    def last_success(self) -> datetime | None:
        return self._last_success

    def _load_cache_if_available(self) -> None:
        if not self.cache_path.is_file():
            return
        try:
            envelope = json.loads(self.cache_path.read_text(encoding="utf-8"))
            fetched_at = _parse_event_time(envelope["fetched_at"])
            events = _parse_rows(envelope["events"])
        except (OSError, KeyError, json.JSONDecodeError, NewsCalendarError):
            return
        self._last_success = fetched_at
        self._events = events

    def _write_cache(self, payload: object, fetched_at: datetime) -> None:
        rows = payload.get("events") if isinstance(payload, dict) else payload
        envelope = {
            "fetched_at": fetched_at.isoformat(),
            "events": rows,
        }
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=self.cache_path.name + ".",
            suffix=".tmp",
            dir=str(self.cache_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.cache_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def refresh(self, now: datetime | None = None) -> tuple[NewsEvent, ...]:
        instant = as_utc(now or datetime.now(timezone.utc), "now")
        self._last_attempt = instant
        request = urllib.request.Request(
            self.url,
            headers={
                "User-Agent": "AAQTS/1.0 economic-calendar risk filter",
                "Accept": "application/json",
            },
        )
        try:
            response = self._opener(request, timeout=self.timeout_seconds)
            raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            events = _parse_rows(payload)
        except Exception as exc:
            raise NewsCalendarError(
                f"Could not refresh economic calendar: {exc}"
            ) from exc

        self._events = events
        self._last_success = instant
        self._write_cache(payload, instant)
        return events

    def _ensure_fresh(self, now: datetime) -> None:
        instant = as_utc(now, "now")
        due = (
            self._last_attempt is None
            or instant - self._last_attempt >= self.refresh_interval
        )
        if due:
            try:
                self.refresh(instant)
            except NewsCalendarError:
                pass

        if self._last_success is None:
            raise NewsCalendarError("No trusted economic calendar is available")
        if instant - self._last_success > self.max_stale:
            raise NewsCalendarError(
                "Economic calendar cache is stale; new entries must remain blocked"
            )

    def events_between(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[NewsEvent, ...]:
        start = as_utc(start_time, "start_time")
        end = as_utc(end_time, "end_time")
        if end < start:
            raise NewsCalendarError("end_time cannot precede start_time")
        self._ensure_fresh(datetime.now(timezone.utc))
        return tuple(
            event for event in self._events if start <= event.event_time <= end
        )


def build_news_provider(
    *,
    enabled: bool,
    calendar_file: str = "",
    calendar_url: str = DEFAULT_FOREX_FACTORY_URL,
    cache_path: str = "runtime/news_calendar_cache.json",
    refresh_minutes: int = 30,
    max_stale_minutes: int = 360,
):
    """Build the configured production provider with explicit precedence."""

    if not enabled:
        return None
    if str(calendar_file).strip():
        return JsonNewsEventProvider(calendar_file)
    return RefreshingNewsEventProvider(
        calendar_url or DEFAULT_FOREX_FACTORY_URL,
        cache_path=cache_path,
        refresh_interval=timedelta(minutes=int(refresh_minutes)),
        max_stale=timedelta(minutes=int(max_stale_minutes)),
    )


__all__ = [
    "DEFAULT_FOREX_FACTORY_URL",
    "JsonNewsEventProvider",
    "NewsCalendarError",
    "RefreshingNewsEventProvider",
    "build_news_provider",
]
