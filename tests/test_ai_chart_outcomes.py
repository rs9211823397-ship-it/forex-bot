from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ai.chart_analysis.config import ChartObserverConfig
from ai.chart_analysis.outcomes import OutcomeEvaluator
from ai.chart_analysis.snapshot import MarketSnapshot


def _snapshot(snapshot_id: str = "EURUSD_X_test") -> MarketSnapshot:
    return MarketSnapshot(
        schema_version="1.0",
        snapshot_id=snapshot_id,
        symbol="EURUSD=X",
        as_of_utc="2026-08-12T00:15:00+00:00",
        lower_timeframe="15m",
        higher_timeframe="1h",
        source="MT5",
        broker_symbol="EURUSDm",
        lower_bars=(
            {
                "open_time": "2026-08-12T00:00:00+00:00",
                "close_time": "2026-08-12T00:15:00+00:00",
                "open": 1.1,
                "high": 1.1005,
                "low": 1.0995,
                "close": 1.1001,
                "volume": 100.0,
            },
        ),
        higher_bars=(),
        lower_indicators={"ATR": 0.001},
        higher_indicators={},
    )


def _future_frame(count: int, *, ambiguous_first: bool = False) -> pd.DataFrame:
    rows = []
    index = []
    for i in range(count + 1):
        open_time = pd.Timestamp("2026-08-12T00:00:00Z") + pd.Timedelta(minutes=15 * i)
        close_time = open_time + pd.Timedelta(minutes=15)
        if i == 0:
            # This candle closes exactly at capture time and must be ignored.
            open_price = 9.0
            high = 9.5
            low = 8.5
            close = 9.1
        else:
            open_price = 1.1000 + (i - 1) * 0.00005
            high = open_price + 0.00035
            low = open_price - 0.00025
            close = open_price + 0.00010
            if i == 1 and ambiguous_first:
                high = 1.1025
                low = 1.0985
        index.append(open_time)
        rows.append(
            {
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100.0,
                "close_time": close_time,
            }
        )
    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(index))
    frame.index.name = "open_time"
    return frame


def _config(tmp_path: Path) -> ChartObserverConfig:
    return ChartObserverConfig(
        enabled=True,
        remote_enabled=False,
        output_root=tmp_path,
        outcomes_enabled=True,
        outcome_horizons=(1, 3, 6, 12),
        outcome_stop_r=1.0,
        outcome_target_r=2.0,
    )


def test_outcomes_use_only_future_bars_and_finalize_once(tmp_path):
    evaluator = OutcomeEvaluator(_config(tmp_path))
    snapshot = _snapshot()
    assert evaluator.register(snapshot, {"signal": "BUY", "confidence": 55}) is True

    assert evaluator.update_market("EURUSD=X", _future_frame(3)) == 1
    outcome_path = tmp_path / "2026-08-12" / snapshot.snapshot_id / "outcome.json"
    partial = json.loads(outcome_path.read_text(encoding="utf-8"))
    assert partial["finalized"] is False
    assert set(partial["horizons"]) == {"1", "3"}
    # The 9.0 candle closes at as_of and is excluded; next-bar open is 1.1000.
    assert partial["levels"]["entry"] == 1.1
    assert partial["levels"]["source"] == "NEXT_BAR_OPEN_SNAPSHOT_ATR"

    assert evaluator.update_market("EURUSD=X", _future_frame(12)) == 1
    final = json.loads(outcome_path.read_text(encoding="utf-8"))
    assert final["finalized"] is True
    assert set(final["horizons"]) == {"1", "3", "6", "12"}
    assert final["policy"]["future_candles_only"] is True

    index_path = tmp_path / "outcomes.jsonl"
    lines = index_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "OUTCOME_FINAL"

    # Finalized observations are removed from pending memory; no duplicate row.
    assert evaluator.update_market("EURUSD=X", _future_frame(12)) == 0
    assert len(index_path.read_text(encoding="utf-8").splitlines()) == 1


def test_same_bar_tp_and_sl_is_ambiguous_not_guessed(tmp_path):
    evaluator = OutcomeEvaluator(_config(tmp_path))
    snapshot = _snapshot("EURUSD_X_ambiguous")
    assert evaluator.register(snapshot, {"signal": "BUY", "confidence": 60}) is True

    evaluator.update_market("EURUSD=X", _future_frame(12, ambiguous_first=True))
    outcome_path = tmp_path / "2026-08-12" / snapshot.snapshot_id / "outcome.json"
    outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
    first = outcome["horizons"]["1"]
    assert first["first_barrier_event"] == "AMBIGUOUS_SAME_BAR"
    assert first["terminal_r"] is None
    assert outcome["final"]["status"] == "AMBIGUOUS_SAME_BAR"
    assert outcome["final"]["realized_r"] is None


def test_restart_recovers_unfinished_input_capture(tmp_path):
    snapshot = _snapshot("EURUSD_X_restart")
    directory = tmp_path / "2026-08-12" / snapshot.snapshot_id
    directory.mkdir(parents=True)
    (directory / "input.json").write_text(
        json.dumps(
            {
                "snapshot": snapshot.to_dict(),
                "deterministic_comparison": {"signal": "BUY", "confidence": 48},
            }
        ),
        encoding="utf-8",
    )

    evaluator = OutcomeEvaluator(_config(tmp_path))
    assert evaluator.status()["pending"] == 1
    assert evaluator.update_market("EURUSD=X", _future_frame(12)) == 1
    assert (directory / "outcome.json").exists()
    assert evaluator.status()["pending"] == 0
