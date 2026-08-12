from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import pytest

from ai.chart_analysis.config import ChartObserverConfig
from ai.chart_analysis.observer import ChartObserver
from ai.chart_analysis.schema import ChartAnalysis
from ai.chart_analysis.snapshot import build_market_snapshot
from ai.chart_analysis.store import ChartObservationStore


def _frame(start: str, periods: int, frequency: str, close_delta: str) -> pd.DataFrame:
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
    frame["close_time"] = frame.index + pd.Timedelta(close_delta)
    frame.attrs["source"] = "MT5"
    frame.attrs["broker_symbol"] = "EURUSDm"
    return frame


def _analysis(snapshot) -> ChartAnalysis:
    return ChartAnalysis(
        schema_version="1.0",
        snapshot_id=snapshot.snapshot_id,
        symbol=snapshot.symbol,
        as_of_utc=snapshot.as_of_utc,
        market_regime="TREND",
        trend_direction="BULLISH",
        higher_timeframe_bias="BULLISH",
        market_structure="BULLISH",
        structure_event="BOS",
        liquidity_event="NONE",
        setup="PULLBACK_CONTINUATION",
        signal="BUY",
        confidence=72.0,
        entry_zone_low=None,
        entry_zone_high=None,
        invalidation_price=None,
        target_1=None,
        target_2=None,
        estimated_rr=None,
        evidence=("causal test evidence",),
        contradictions=(),
        data_quality="GOOD",
        abstain=False,
    )


def test_snapshot_truncates_higher_timeframe_to_lower_as_of():
    lower = _frame("2026-08-12T00:00:00Z", 3, "15min", "15min")
    higher = _frame("2026-08-11T23:00:00Z", 3, "1h", "1h")

    snapshot = build_market_snapshot(
        symbol="EURUSD=X",
        lower_frame=lower,
        higher_frame=higher,
        lower_timeframe="15m",
        higher_timeframe="1h",
        numeric_bars=24,
    )

    assert snapshot.as_of_utc == "2026-08-12T00:45:00+00:00"
    assert snapshot.lower_bars[-1]["close_time"] == snapshot.as_of_utc
    assert snapshot.higher_bars[-1]["close_time"] == "2026-08-12T00:00:00+00:00"
    assert all(item["close_time"] <= snapshot.as_of_utc for item in snapshot.higher_bars)


def test_chart_analysis_rejects_snapshot_identity_mismatch():
    lower = _frame("2026-08-12T00:00:00Z", 3, "15min", "15min")
    higher = _frame("2026-08-11T22:00:00Z", 3, "1h", "1h")
    snapshot = build_market_snapshot(
        symbol="EURUSD=X",
        lower_frame=lower,
        higher_frame=higher,
        lower_timeframe="15m",
        higher_timeframe="1h",
    )
    payload = _analysis(snapshot).to_dict()
    payload["snapshot_id"] = "wrong-snapshot"

    with pytest.raises(ValueError, match="snapshot_id mismatch"):
        ChartAnalysis.from_payload(
            payload,
            expected_snapshot_id=snapshot.snapshot_id,
            expected_symbol=snapshot.symbol,
            expected_as_of_utc=snapshot.as_of_utc,
        )


class _FakeRenderer:
    def render(self, frame, *, symbol, timeframe, as_of_utc, output_path):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-png")
        return path


class _FakeClient:
    def __init__(self):
        self.snapshots = []

    def analyze(self, snapshot, lower_image, higher_image):
        self.snapshots.append(snapshot.to_dict())
        return _analysis(snapshot), {
            "response_id": "test-response",
            "model": "fake-vision-model",
            "status": "completed",
            "latency_ms": 1.0,
            "usage": {},
        }


def _wait_idle(observer: ChartObserver) -> None:
    deadline = time.time() + 3.0
    while time.time() < deadline:
        if observer.status()["pending"] == 0:
            return
        time.sleep(0.01)
    raise AssertionError("observer did not become idle")


def test_observer_is_deduplicated_and_blind_to_deterministic_decision(tmp_path):
    config = ChartObserverConfig(
        enabled=True,
        remote_enabled=True,
        output_root=tmp_path,
        only_actionable=True,
        max_inflight=1,
        lower_render_bars=64,
        higher_render_bars=64,
        numeric_bars=12,
    )
    client = _FakeClient()
    store = ChartObservationStore(config)
    observer = ChartObserver(
        config,
        renderer=_FakeRenderer(),
        client=client,
        store=store,
    )
    lower = _frame("2026-08-12T00:00:00Z", 40, "15min", "15min")
    higher = _frame("2026-08-11T12:00:00Z", 12, "1h", "1h")
    deterministic = {
        "signal": "BUY",
        "confidence": 55,
        "secret_marker": "DETERMINISTIC_ONLY_DO_NOT_SEND",
    }

    try:
        assert observer.observe(
            symbol="EURUSD=X",
            lower_frame=lower,
            higher_frame=higher,
            deterministic=deterministic,
            lower_timeframe="15m",
            higher_timeframe="1h",
        ) is True
        _wait_idle(observer)
        assert observer.observe(
            symbol="EURUSD=X",
            lower_frame=lower,
            higher_frame=higher,
            deterministic=deterministic,
            lower_timeframe="15m",
            higher_timeframe="1h",
        ) is False

        status = observer.status()
        assert status["submitted"] == 1
        assert status["completed"] == 1
        assert status["errors"] == 0
        assert len(client.snapshots) == 1
        assert "DETERMINISTIC_ONLY_DO_NOT_SEND" not in json.dumps(client.snapshots[0])

        index = (tmp_path / "observations.jsonl").read_text(encoding="utf-8")
        assert '"status":"COMPLETED"' in index
        input_files = list(tmp_path.glob("*/*/input.json"))
        assert len(input_files) == 1
        stored = json.loads(input_files[0].read_text(encoding="utf-8"))
        assert stored["deterministic_comparison"]["secret_marker"] == deterministic["secret_marker"]
    finally:
        observer.shutdown(wait=True)


def test_observer_actionable_gate_skips_hold_without_remote_work(tmp_path):
    config = ChartObserverConfig(
        enabled=True,
        output_root=tmp_path,
        only_actionable=True,
        max_inflight=1,
    )
    client = _FakeClient()
    observer = ChartObserver(
        config,
        renderer=_FakeRenderer(),
        client=client,
        store=ChartObservationStore(config),
    )
    lower = _frame("2026-08-12T00:00:00Z", 40, "15min", "15min")
    higher = _frame("2026-08-11T12:00:00Z", 12, "1h", "1h")
    try:
        assert observer.observe(
            symbol="EURUSD=X",
            lower_frame=lower,
            higher_frame=higher,
            deterministic={"signal": "HOLD", "confidence": 0},
            lower_timeframe="15m",
            higher_timeframe="1h",
        ) is False
        assert client.snapshots == []
        assert observer.status()["submitted"] == 0
    finally:
        observer.shutdown(wait=True)
