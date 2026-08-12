from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path

import pandas as pd

from ai.chart_analysis.config import ChartObserverConfig
from ai.chart_analysis.observer import ChartObserver
from ai.chart_analysis.store import ChartObservationStore


def _frame(start: str, periods: int, frequency: str, close_delta: timedelta) -> pd.DataFrame:
    index = pd.date_range(start=start, periods=periods, freq=frequency, tz="UTC")
    base = pd.Series(range(periods), dtype=float).to_numpy() * 0.001 + 1.1
    frame = pd.DataFrame(
        {
            "open": base,
            "high": base + 0.0008,
            "low": base - 0.0008,
            "close": base + 0.0002,
            "volume": 100.0,
        },
        index=index,
    )
    frame.index.name = "open_time"
    frame["close_time"] = frame.index + close_delta
    frame.attrs["source"] = "MT5"
    frame.attrs["broker_symbol"] = "EURUSDm"
    return frame


class _FakeRenderer:
    def render(self, frame, *, symbol, timeframe, as_of_utc, output_path):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-png")
        return path


class _ForbiddenClient:
    def analyze(self, *args, **kwargs):
        raise AssertionError("capture-only mode must not call the remote client")


def _wait_idle(observer: ChartObserver) -> None:
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if observer.status()["pending"] == 0:
            return
        time.sleep(0.01)
    raise AssertionError("observer did not become idle")


def test_capture_only_writes_evidence_without_remote_call(tmp_path):
    config = ChartObserverConfig(
        enabled=True,
        remote_enabled=False,
        output_root=tmp_path,
        only_actionable=True,
        max_inflight=1,
        lower_render_bars=64,
        higher_render_bars=64,
        numeric_bars=12,
    )
    observer = ChartObserver(
        config,
        renderer=_FakeRenderer(),
        client=_ForbiddenClient(),
        store=ChartObservationStore(config),
    )
    lower = _frame("2026-08-12T00:00:00Z", 40, "15min", timedelta(minutes=15))
    higher = _frame("2026-08-11T12:00:00Z", 12, "1h", timedelta(hours=1))

    try:
        assert observer.observe(
            symbol="EURUSD=X",
            lower_frame=lower,
            higher_frame=higher,
            deterministic={"signal": "BUY", "confidence": 55},
            lower_timeframe="15m",
            higher_timeframe="1h",
        ) is True
        _wait_idle(observer)

        status = observer.status()
        assert status["remote_enabled"] is False
        assert status["submitted"] == 1
        assert status["captured"] == 1
        assert status["completed"] == 0
        assert status["errors"] == 0
        assert status["analytics"]["enabled"] is True

        assert len(list(tmp_path.glob("*/*/input.json"))) == 1
        assert len(list(tmp_path.glob("*/*/capture.json"))) == 1
        assert len(list(tmp_path.glob("*/*/m15.png"))) == 1
        assert len(list(tmp_path.glob("*/*/h1.png"))) == 1
        assert len(list(tmp_path.glob("*/*/analysis.json"))) == 0
        assert (tmp_path / "analytics_summary.json").exists()
        index = (tmp_path / "observations.jsonl").read_text(encoding="utf-8")
        assert '"status":"CAPTURED"' in index
        assert '"status":"ERROR"' not in index
    finally:
        observer.shutdown(wait=True)
