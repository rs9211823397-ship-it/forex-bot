import io
import json
from datetime import datetime, timedelta, timezone

import pytest

from risk.news_calendar import NewsCalendarError, RefreshingNewsEventProvider


class Response:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw


def test_forex_factory_rows_are_normalized_and_filtered(tmp_path):
    payload = [
        {
            "title": "Non-Farm Employment Change",
            "country": "USD",
            "date": "2026-08-07T08:30:00-04:00",
            "impact": "High",
            "forecast": "",
            "previous": "",
        },
        {
            "title": "Bank Holiday",
            "country": "CAD",
            "date": "2026-08-07T00:00:00-04:00",
            "impact": "Holiday",
        },
    ]

    provider = RefreshingNewsEventProvider(
        "https://example.test/calendar.json",
        cache_path=tmp_path / "calendar.json",
        opener=lambda request, timeout: Response(payload),
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    events = provider.refresh(now)

    assert len(events) == 1
    assert events[0].impact == "HIGH"
    assert events[0].currencies == ("USD",)
    assert events[0].name == "Non-Farm Employment Change"
    assert provider.last_success == now


def test_remote_success_is_atomically_cached_and_reusable(tmp_path):
    fetched = datetime.now(timezone.utc)
    event_time = fetched + timedelta(hours=2)
    payload = [
        {
            "title": "CPI",
            "country": "USD",
            "date": event_time.isoformat(),
            "impact": "High",
        }
    ]
    cache = tmp_path / "calendar.json"
    provider = RefreshingNewsEventProvider(
        "https://example.test/calendar.json",
        cache_path=cache,
        opener=lambda request, timeout: Response(payload),
    )
    provider.refresh(fetched)
    assert cache.is_file()

    def offline(request, timeout):
        raise OSError("offline")

    fallback = RefreshingNewsEventProvider(
        "https://example.test/calendar.json",
        cache_path=cache,
        refresh_interval=timedelta(minutes=30),
        max_stale=timedelta(hours=6),
        opener=offline,
    )
    events = fallback.events_between(
        fetched - timedelta(hours=1), fetched + timedelta(days=3)
    )
    assert len(events) == 1
    assert events[0].name == "CPI"


def test_no_remote_and_no_cache_fails_closed(tmp_path):
    def offline(request, timeout):
        raise OSError("offline")

    provider = RefreshingNewsEventProvider(
        "https://example.test/calendar.json",
        cache_path=tmp_path / "missing.json",
        opener=offline,
    )
    with pytest.raises(NewsCalendarError, match="No trusted economic calendar"):
        provider.events_between(
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(hours=1),
        )


def test_stale_cache_fails_closed(tmp_path):
    cache = tmp_path / "calendar.json"
    old = datetime.now(timezone.utc) - timedelta(hours=8)
    cache.write_text(
        json.dumps(
            {
                "fetched_at": old.isoformat(),
                "events": [
                    {
                        "title": "CPI",
                        "country": "USD",
                        "date": datetime.now(timezone.utc).isoformat(),
                        "impact": "High",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def offline(request, timeout):
        raise OSError("offline")

    provider = RefreshingNewsEventProvider(
        "https://example.test/calendar.json",
        cache_path=cache,
        max_stale=timedelta(hours=6),
        opener=offline,
    )
    with pytest.raises(NewsCalendarError, match="stale"):
        provider.events_between(
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) + timedelta(hours=1),
        )


def test_bad_remote_payload_does_not_replace_good_cache(tmp_path):
    cache = tmp_path / "calendar.json"
    good_payload = [
        {
            "title": "CPI",
            "country": "USD",
            "date": "2026-08-05T12:30:00+00:00",
            "impact": "High",
        }
    ]
    provider = RefreshingNewsEventProvider(
        "https://example.test/calendar.json",
        cache_path=cache,
        opener=lambda request, timeout: Response(good_payload),
    )
    fetched = datetime.now(timezone.utc)
    provider.refresh(fetched)
    original = cache.read_bytes()

    bad = RefreshingNewsEventProvider(
        "https://example.test/calendar.json",
        cache_path=cache,
        opener=lambda request, timeout: Response({"not": "a list"}),
    )
    with pytest.raises(NewsCalendarError):
        bad.refresh(fetched + timedelta(minutes=31))

    assert cache.read_bytes() == original


def test_refresh_lock_allows_one_remote_fetch(tmp_path):
    calls = []

    def opener(request, timeout):
        calls.append(1)
        return Response(
            [
                {
                    "title": "CPI",
                    "country": "USD",
                    "date": "2026-08-05T12:30:00+00:00",
                    "impact": "High",
                }
            ]
        )

    provider = RefreshingNewsEventProvider(
        "https://example.test/calendar.json",
        cache_path=tmp_path / "calendar.json",
        opener=opener,
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    provider.refresh(now)
    provider.refresh(now + timedelta(minutes=1))

    assert len(calls) == 1
