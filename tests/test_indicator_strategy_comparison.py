from __future__ import annotations

import argparse
import numpy as np
import pandas as pd
import pytest

from backtesting.indicator_comparison import (
    BUY,
    SELL,
    ComparisonConfig,
    IndicatorEvent,
    simulate_indicator_strategy,
    strategy_metrics_with_holdout,
    ut_bot_ema200_events,
    vwap_ema9_events,
)
from scripts.compare_utbot_vwap import _symbol_universe, _winner, run


def _frame(
    closes: list[float] | np.ndarray,
    *,
    opens: list[float] | np.ndarray | None = None,
    start: str = "2026-01-01T00:00:00Z",
    volume: float = 100.0,
) -> pd.DataFrame:
    close = np.asarray(closes, dtype=float)
    open_values = close.copy() if opens is None else np.asarray(opens, dtype=float)
    index = pd.date_range(start, periods=len(close), freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "open": open_values,
            "high": np.maximum(open_values, close) + 0.25,
            "low": np.minimum(open_values, close) - 0.25,
            "close": close,
            "volume": volume,
            "close_time": index + pd.Timedelta(minutes=15),
        },
        index=index,
    )


def test_all_means_the_thirteen_enabled_research_symbols() -> None:
    symbols = _symbol_universe("ALL", include_paper_only=False)

    assert len(symbols) == 13
    assert symbols == [
        "EURUSD=X",
        "GBPUSD=X",
        "JPY=X",
        "CHF=X",
        "CAD=X",
        "AUDUSD=X",
        "NZDUSD=X",
        "GC=F",
        "SI=F",
        "PL=F",
        "PA=F",
        "BTC-USD",
        "ETH-USD",
    ]


def test_ut_bot_ema_filter_controls_entry_but_preserves_raw_exit_event() -> None:
    # The first post-warmup BUY is above EMA200 and may enter.  The later SELL
    # is deliberately above EMA200: it must still exist to close the BUY, but
    # it must not open a new SELL.
    prices = np.r_[np.linspace(100.0, 90.0, 210), 100.0, 110.0, 120.0, 130.0, 140.0]
    events, diagnostics = ut_bot_ema200_events(
        _frame(prices),
        key_value=3.0,
        atr_period=10,
        ema_period=200,
    )
    buy_index = next(index for index, event in enumerate(events) if event and event.side == BUY and event.entry_allowed)

    assert prices[buy_index] > diagnostics["EMA_200"].iloc[buy_index]

    reversal = np.r_[prices, 135.0, 125.0, 115.0, 105.0]
    events, diagnostics = ut_bot_ema200_events(
        _frame(reversal),
        key_value=3.0,
        atr_period=10,
        ema_period=200,
    )
    sell_index = next(index for index in range(buy_index + 1, len(events)) if events[index] and events[index].side == SELL)

    assert reversal[sell_index] > diagnostics["EMA_200"].iloc[sell_index]
    assert events[sell_index] == IndicatorEvent(SELL, entry_allowed=False)


def test_vwap_ema9_crosses_and_does_not_invent_session_boundary_signal() -> None:
    prices = [100.0] * 9 + [90.0, 90.0, 90.0, 120.0, 120.0, 120.0, 80.0, 80.0]
    events, diagnostics = vwap_ema9_events(_frame(prices))

    observed = [(index, event.side) for index, event in enumerate(events) if event]
    assert observed == [(9, SELL), (12, BUY), (16, SELL)]
    assert diagnostics["VWAP_SESSION"].nunique() == 1

    # A fresh UTC-day VWAP anchor can jump across EMA9.  That reset alone is
    # not a tradable crossover.
    boundary_frame = _frame(
        [100.0] * 8 + [80.0, 120.0],
        start="2026-01-01T21:45:00Z",
    )
    boundary_events, boundary_diagnostics = vwap_ema9_events(boundary_frame)
    sessions = boundary_diagnostics["VWAP_SESSION"]
    boundary = next(
        index
        for index in range(1, len(sessions))
        if sessions.iloc[index] != sessions.iloc[index - 1]
    )
    assert boundary_events[boundary] is None


def test_confirmed_event_fills_at_next_open_and_opposite_event_exits() -> None:
    frame = _frame(
        [100.0, 101.0, 102.0, 103.0, 104.0],
        opens=[100.0, 101.0, 110.0, 103.0, 90.0],
    )
    events = [None, IndicatorEvent(BUY), None, IndicatorEvent(SELL, False), None]
    trades, metrics = simulate_indicator_strategy(
        frame,
        events,
        strategy_name="TEST",
        symbol="TEST",
        config=ComparisonConfig(round_trip_cost_bps=0.0, catastrophe_stop_percent=20.0),
    )

    assert len(trades) == 1
    assert trades[0]["side"] == BUY
    assert trades[0]["entry_price"] == 110.0
    assert trades[0]["exit_price"] == 90.0
    assert trades[0]["exit_reason"] == "OPPOSITE_SIGNAL"
    assert trades[0]["entry_time"] == frame.index[2]
    assert trades[0]["exit_time"] == frame.index[4]
    assert metrics["completed_trades"] == 1


def test_catastrophe_stop_is_identical_for_both_strategy_event_streams() -> None:
    frame = _frame(
        [100.0, 100.0, 100.0],
        opens=[100.0, 100.0, 100.0],
    )
    frame.loc[frame.index[1], "low"] = 98.0
    events = [IndicatorEvent(BUY), None, None]
    config = ComparisonConfig(round_trip_cost_bps=5.0, catastrophe_stop_percent=1.0)

    first, _ = simulate_indicator_strategy(frame, events, strategy_name="UT", symbol="X", config=config)
    second, _ = simulate_indicator_strategy(frame, events, strategy_name="VWAP", symbol="X", config=config)

    assert first[0]["exit_price"] == pytest.approx(99.0)
    assert first[0]["exit_reason"] == "CATASTROPHE_STOP"
    assert first[0]["net_return"] == second[0]["net_return"]


def test_stop_gap_uses_the_less_favorable_open_instead_of_stop_price() -> None:
    frame = _frame(
        [100.0, 100.0, 95.0],
        opens=[100.0, 100.0, 95.0],
    )
    events = [IndicatorEvent(BUY), None, None]
    trades, _ = simulate_indicator_strategy(
        frame,
        events,
        strategy_name="TEST",
        symbol="TEST",
        config=ComparisonConfig(round_trip_cost_bps=0.0, catastrophe_stop_percent=1.0),
    )

    assert trades[0]["exit_price"] == 95.0
    assert trades[0]["exit_reason"] == "CATASTROPHE_STOP_GAP"


def test_past_events_are_unchanged_when_future_candles_are_mutated() -> None:
    base = _frame(np.sin(np.arange(280) / 5.0) * 5.0 + 100.0)
    changed = base.copy()
    changed.loc[changed.index[240]:, ["open", "high", "low", "close"]] *= 2.0

    base_ut, _ = ut_bot_ema200_events(base)
    changed_ut, _ = ut_bot_ema200_events(changed)
    base_vwap, _ = vwap_ema9_events(base)
    changed_vwap, _ = vwap_ema9_events(changed)

    assert base_ut[:240] == changed_ut[:240]
    assert base_vwap[:240] == changed_vwap[:240]


def test_holdout_uses_chronological_tail_and_winner_requires_both_samples() -> None:
    frame = _frame(np.linspace(100.0, 130.0, 20))
    events = [None] * len(frame)
    events[1] = IndicatorEvent(BUY)
    events[10] = IndicatorEvent(SELL)
    events[12] = IndicatorEvent(BUY)
    events[14] = IndicatorEvent(SELL)
    trades, report = strategy_metrics_with_holdout(
        frame,
        events,
        strategy_name="TEST",
        symbol="TEST",
        config=ComparisonConfig(round_trip_cost_bps=0.0, catastrophe_stop_percent=20.0),
        holdout_fraction=0.30,
    )

    assert len(trades) >= 2
    assert report["split_time"] == frame.index[14].isoformat()
    assert report["out_of_sample"]["completed_trades"] == 1

    enough = {"completed_trades": 10, "net_return_percent": 2.0, "profit_factor": 1.2, "max_drawdown_percent": 3.0}
    sparse = {"completed_trades": 9, "net_return_percent": 20.0, "profit_factor": 9.0, "max_drawdown_percent": 1.0}
    assert _winner(enough, sparse, min_trades=10) == "INSUFFICIENT_OOS_SAMPLE"


def test_csv_cli_pipeline_writes_auditable_comparison_outputs(tmp_path) -> None:
    csv_dir = tmp_path / "csv"
    output_dir = tmp_path / "report"
    csv_dir.mkdir()
    frame = _frame(np.sin(np.arange(320) / 6.0) * 4.0 + 100.0)
    frame.reset_index(names="open_time").to_csv(csv_dir / "EURUSD=X.csv", index=False)
    args = argparse.Namespace(
        symbols="EURUSD",
        provider="MT5",
        csv_dir=str(csv_dir),
        timeframe="15m",
        lookback_bars=300,
        initial_equity=1_000.0,
        stop_percent=1.0,
        cost_bps=5.0,
        holdout_percent=30.0,
        min_oos_trades=1,
        ut_key=3.0,
        ut_atr=10,
        include_paper_only=False,
        output_dir=str(output_dir),
    )

    report = run(args)

    assert report["overall"]["successful_symbols"] == 1
    assert report["symbols"][0]["dataset_sha256"]
    assert report["overall"]["aggregate_oos"]["UT_BOT_EMA200"]["symbols"] == 1
    assert (output_dir / "utbot_vwap_report.md").is_file()
    assert (output_dir / "utbot_vwap_report.json").is_file()
    assert (output_dir / "utbot_vwap_metrics.csv").is_file()
    assert (output_dir / "utbot_vwap_trades.csv").is_file()
