import json
from datetime import datetime, timedelta, timezone

import pytest

from main import TradingApplication
from risk.news_calendar import JsonNewsEventProvider, NewsCalendarError


BASE = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


def test_json_news_calendar_is_strict_sorted_and_time_bounded(tmp_path):
    path = tmp_path / "calendar.json"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "event_time": "2026-08-03T13:00:00Z",
                        "impact": "HIGH",
                        "currencies": ["USD"],
                        "name": "CPI",
                    },
                    {
                        "event_time": "2026-08-03T12:30:00+00:00",
                        "impact": "MEDIUM",
                        "currencies": ["EUR"],
                        "name": "Survey",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    provider = JsonNewsEventProvider(path)
    events = provider.events_between(
        BASE + timedelta(minutes=20),
        BASE + timedelta(minutes=40),
    )

    assert [event.name for event in provider.events] == ["Survey", "CPI"]
    assert [event.name for event in events] == ["Survey"]


def test_invalid_news_calendar_is_rejected(tmp_path):
    path = tmp_path / "calendar.json"
    path.write_text('{"events": [{"impact": "HIGH"}]}', encoding="utf-8")

    with pytest.raises(NewsCalendarError, match="event 0"):
        JsonNewsEventProvider(path)


def test_currency_exposure_mapping_covers_forex_gold_and_crypto():
    assert [
        (item.currency, item.direction)
        for item in TradingApplication._currency_exposures("EURUSD=X", "BUY")
    ] == [("EUR", 1), ("USD", -1)]
    assert [
        (item.currency, item.direction)
        for item in TradingApplication._currency_exposures("GC=F", "SELL")
    ] == [("XAU", -1), ("USD", 1)]
    assert [
        (item.currency, item.direction)
        for item in TradingApplication._currency_exposures("BTC-USD", "BUY")
    ] == [("BTC", 1), ("USD", -1)]
