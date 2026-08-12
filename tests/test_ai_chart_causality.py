from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import pandas as pd

from ai.chart_analysis.config import ChartObserverConfig
from ai.chart_analysis.observer import ChartObserver
from ai.chart_analysis.schema import ChartAnalysis
from ai.chart_analysis.store import ChartObservationStore


def _frame(start: str, periods: int, frequency: str, close_delta: timedelta) -> pd.DataFrame:
    index = pd.date_range(start=start, periods=periods, freq=frequency, tz="UTC")
    values = [1.10 + index * 0.001 for index in range(periods)]
    frame = pd.DataFrame(
        {
            "open": values,
            "high": [value + 0.0008 for value in values],
            "low": [value - 0.0008 for value in values],
            "close": [value + 0.0002 for value in values],
            "volume": 100.0,
        },
        index=index,
    )
    frame["close_time"] = frame.index + close_delta
    frame.attrs["source"] = "MT5"
    return frame


class _GuardIndicators:
    def __init__(self):
        self.max_close_times = []

    def add_indicators(self, frame):
        self.max_close_times.append(pd.to_datetime(frame["close_time"], utc=True).max())
        return frame.copy()


class _Renderer:
    def render(self, frame, *, symbol, timeframe, as_of_utc, output_path):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        return path


class _Client:
    def analyze(self, snapshot, lower_image, higher_image):
        return ChartAnalysis(
            schema_version="1.0",
            snapshot_id=snapshot.snapshot_id,
            symbol=snapshot.symbol,
            as_of_utc=snapshot.as_of_utc,
            market_regime="UNKNOWN",
            trend_direction="UNKNOWN",
            higher_timeframe_bias="UNKNOWN",
            market_structure="UNKNOWN",
            structure_event="NONE",
            liquidity_event="NONE",
            setup="NO_SETUP",
            signal="HOLD",
            confidence=0.0,
            entry_zone_low=None,
            entry_zone_high=None,
            invalidation_price=None,
            target_1=None,
            target_2=None,
            estimated_rr=None,
            evidence=(),
            contradictions=(),
            data_quality="GOOD",
            abstain=True,
        ), {"model": "fake", "status": "completed", "usage": {}}


def test_observer_removes_future_h1_rows_before_indicator_calculation(tmp_path):
    config = ChartObserverConfig(
        enabled=True,
        output_root=tmp_path,
        only_actionable=True,
        max_inflight=1,
    )
    observer = ChartObserver(
        config,
        renderer=_Renderer(),
        client=_Client(),
        store=ChartObservationStore(config),
    )
    guard = _GuardIndicators()
    observer.indicators = guard

    lower = _frame("2026-08-12T00:00:00Z", 3, "15min", timedelta(minutes=15))
    # Two of these H1 candles close after the M15 as_of=00:45 and must never
    # enter the indicator function.
    higher = _frame("2026-08-11T22:00:00Z", 4, "1h", timedelta(hours=1))

    try:
        assert observer.observe(
            symbol="EURUSD=X",
            lower_frame=lower,
            higher_frame=higher,
            deterministic={"signal": "BUY", "confidence": 50},
            lower_timeframe="15m",
            higher_timeframe="1h",
        )
        deadline = time.time() + 3.0
        while observer.status()["pending"] and time.time() < deadline:
            time.sleep(0.01)

        assert observer.status()["errors"] == 0
        assert len(guard.max_close_times) == 2
        cutoff = pd.Timestamp("2026-08-12T00:45:00Z")
        assert all(close_time <= cutoff for close_time in guard.max_close_times)
        assert guard.max_close_times[1] == pd.Timestamp("2026-08-12T00:00:00Z")
    finally:
        observer.shutdown(wait=True)
