from __future__ import annotations

import json

import pytest

from ai.chart_analysis.config import ChartObserverConfig
from ai.chart_analysis.replay import HistoricalChartReplay
from ai.chart_analysis.store import ChartObservationStore


class _FakeAnalysis:
    signal = "BUY"
    confidence = 70.0
    abstain = False

    def to_dict(self):
        return {
            "schema_version": "1.0",
            "snapshot_id": "sample",
            "symbol": "EURUSD=X",
            "as_of_utc": "2026-08-12T00:00:00+00:00",
            "market_regime": "TREND",
            "trend_direction": "BULLISH",
            "higher_timeframe_bias": "BULLISH",
            "market_structure": "BULLISH",
            "structure_event": "BOS",
            "liquidity_event": "NONE",
            "setup": "PULLBACK_CONTINUATION",
            "signal": self.signal,
            "confidence": self.confidence,
            "entry_zone_low": None,
            "entry_zone_high": None,
            "invalidation_price": None,
            "target_1": None,
            "target_2": None,
            "estimated_rr": None,
            "evidence": ["test"],
            "contradictions": [],
            "data_quality": "GOOD",
            "abstain": self.abstain,
        }


class _FakeClient:
    def __init__(self):
        self.calls = 0

    def analyze(self, snapshot, lower_image, higher_image):
        self.calls += 1
        assert snapshot.snapshot_id == "sample"
        assert lower_image.name == "m15.png"
        assert higher_image.name == "h1.png"
        return _FakeAnalysis(), {
            "response_id": "fake-response",
            "model": "fake-model",
            "status": "completed",
            "latency_ms": 1.0,
            "usage": {},
        }


def _write_capture(root):
    directory = root / "2026-08-12" / "sample"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "m15.png").write_bytes(b"m15")
    (directory / "h1.png").write_bytes(b"h1")
    (directory / "input.json").write_text(
        json.dumps(
            {
                "snapshot": {
                    "schema_version": "1.0",
                    "snapshot_id": "sample",
                    "symbol": "EURUSD=X",
                    "as_of_utc": "2026-08-12T00:00:00+00:00",
                    "lower_timeframe": "15m",
                    "higher_timeframe": "1h",
                    "source": "MT5",
                    "broker_symbol": "EURUSDm",
                    "lower_bars": [],
                    "higher_bars": [],
                    "lower_indicators": {},
                    "higher_indicators": {},
                },
                "deterministic_comparison": {
                    "signal": "BUY",
                    "confidence": 55,
                },
                "images": {
                    "lower": "m15.png",
                    "higher": "h1.png",
                },
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_historical_replay_is_idempotent_and_writes_analysis(tmp_path):
    directory = _write_capture(tmp_path)
    config = ChartObserverConfig(
        output_root=tmp_path,
        remote_enabled=True,
    )
    client = _FakeClient()
    replay = HistoricalChartReplay(
        config,
        client=client,
        store=ChartObservationStore(config),
    )

    assert len(replay.pending_paths()) == 1
    result = replay.run(limit=1)

    assert result["completed"] == 1
    assert result["errors"] == 0
    assert result["remaining"] == 0
    assert client.calls == 1
    assert (directory / "analysis.json").exists()

    second = replay.run(limit=1)
    assert second["requested"] == 0
    assert client.calls == 1


def test_historical_replay_refuses_remote_calls_when_disabled(tmp_path):
    _write_capture(tmp_path)
    config = ChartObserverConfig(
        output_root=tmp_path,
        remote_enabled=False,
    )
    client = _FakeClient()
    replay = HistoricalChartReplay(
        config,
        client=client,
        store=ChartObservationStore(config),
    )

    with pytest.raises(RuntimeError, match="REMOTE_ENABLED=true"):
        replay.run(limit=1)
    assert client.calls == 0
