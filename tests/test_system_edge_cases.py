"""Cross-module causal and fail-closed regression tests.

These tests intentionally exercise public contracts across the Phase 3--8
layers.  All fixtures are synthetic and deterministic.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data.timeframes import TimeframeError
from risk.protection import (
    ClosedTradeOutcome,
    PortfolioRiskManager,
    ProtectionConfig,
    RiskAction,
    RiskContext,
    TradeRiskRequest,
)
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from structure.market_structure import BULLISH, MarketStructure


DECISION_TIME = datetime(2025, 1, 8, 12, tzinfo=timezone.utc)


def _structure_frame():
    close = [1.5, 3.0, 2.0, 4.0, 3.0, 5.0, 6.5, 6.2]
    frame = pd.DataFrame(
        {
            "open": close,
            "high": [2.0, 4.0, 3.0, 5.0, 4.0, 6.0, 7.0, 6.8],
            "low": [1.0, 2.0, 1.5, 3.0, 2.5, 4.0, 4.5, 5.8],
            "close": close,
            "close_time": pd.date_range(
                "2025-01-01T00:00:00Z",
                periods=len(close),
                freq="h",
            ),
        }
    )
    frame.attrs["timeframe"] = "1h"
    return frame


def _risk_request(**overrides):
    values = {
        "decision_time": DECISION_TIME,
        "symbol": "EURUSD",
        "direction": "BUY",
        "requested_quantity": 10.0,
        "risk_amount": 100.0,
        "equity": 10_000.0,
    }
    values.update(overrides)
    return TradeRiskRequest(**values)


def test_structure_swing_is_unavailable_until_confirmation_close():
    frame = _structure_frame().iloc[:3].copy()
    structure = MarketStructure(lookback=1)

    before_confirmation = structure.state(
        frame,
        decision_time=frame["close_time"].iloc[1],
        timeframe="1h",
    )
    at_confirmation = structure.state(
        frame,
        decision_time=frame["close_time"].iloc[2],
        timeframe="1h",
    )

    assert before_confirmation.swings == ()
    assert len(at_confirmation.swings) == 1
    assert at_confirmation.swings[0].formed_at == frame["close_time"].iloc[1]
    assert (
        at_confirmation.swings[0].confirmed_at
        == frame["close_time"].iloc[2]
    )


def test_structure_future_mutation_cannot_change_historical_snapshot():
    frame = _structure_frame()
    decision_time = frame["close_time"].iloc[6]
    mutated = frame.copy(deep=True)
    mutated.loc[7, ["open", "high", "low", "close"]] = [
        500.0,
        900.0,
        0.1,
        800.0,
    ]
    structure = MarketStructure(lookback=1)

    original = structure.state(
        frame,
        decision_time=decision_time,
        timeframe="1h",
    )
    changed = structure.state(
        mutated,
        decision_time=decision_time,
        timeframe="1h",
    )

    assert original == changed
    assert original.trend == BULLISH


def test_structure_break_is_close_confirmed_and_not_duplicated():
    frame = _structure_frame()
    structure = MarketStructure(lookback=1)

    state = structure.state(frame, timeframe="1h")

    bullish_bos = [
        event
        for event in state.breaks
        if event.event == "BOS" and event.direction == "BULLISH"
    ]
    assert len(bullish_bos) == 1
    assert bullish_bos[0].close > bullish_bos[0].level

    wick_only = frame.iloc[:7].copy()
    wick_only.loc[6, ["open", "high", "low", "close"]] = [
        4.8,
        7.0,
        4.5,
        4.9,
    ]
    no_close_break = structure.state(wick_only, timeframe="1h")

    assert not any(event.event == "BOS" for event in no_close_break.breaks)


def test_structure_rejects_duplicate_and_non_monotonic_timestamps():
    duplicate = _structure_frame()
    duplicate.loc[2, "close_time"] = duplicate.loc[1, "close_time"]
    non_monotonic = _structure_frame()
    non_monotonic.loc[2, "close_time"] = (
        non_monotonic.loc[1, "close_time"] - pd.Timedelta(minutes=1)
    )
    structure = MarketStructure(lookback=1)

    with pytest.raises(ValueError, match="unique"):
        structure.state(duplicate, timeframe="1h")
    with pytest.raises(ValueError, match="monotonic"):
        structure.state(non_monotonic, timeframe="1h")


def test_future_realized_losses_cannot_block_historical_risk_decision():
    manager = PortfolioRiskManager(
        ProtectionConfig(
            max_daily_loss_percent=1.0,
            max_consecutive_losses=1,
        )
    )
    baseline = manager.assess(_risk_request(), RiskContext())
    future_loss = ClosedTradeOutcome(
        DECISION_TIME + timedelta(seconds=1),
        -10_000.0,
    )
    with_future_state = manager.assess(
        _risk_request(),
        RiskContext(closed_trades=(future_loss,)),
    )

    assert baseline == with_future_state
    assert with_future_state.action is RiskAction.ALLOW


def test_risk_outcome_at_exact_decision_boundary_is_visible():
    manager = PortfolioRiskManager(
        ProtectionConfig(max_daily_loss_percent=1.0)
    )
    assessment = manager.assess(
        _risk_request(),
        RiskContext(
            closed_trades=(
                ClosedTradeOutcome(DECISION_TIME, -100.0),
            )
        ),
    )

    assert assessment.action is RiskAction.BLOCK
    assert assessment.reason_codes == ("DAILY_LOSS_LIMIT",)


def test_strict_mtf_rejects_malformed_timestamp_contract():
    higher = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1.0, 1.0],
        },
        index=pd.DatetimeIndex(
            [
                "2025-01-01T01:00:00Z",
                "2025-01-01T00:00:00Z",
            ]
        ),
    )
    higher.attrs["timeframe"] = "1h"
    lower = higher.iloc[:1].copy()
    lower.attrs["timeframe"] = "15m"
    analyzer = MultiTimeframeAnalyzer.production("1h", "15m")

    with pytest.raises(TimeframeError, match="monotonic"):
        analyzer.analyze(
            higher,
            lower,
            decision_time="2025-01-01T03:00:00Z",
        )


def test_strict_mtf_excludes_all_htf_candles_before_first_close():
    higher = pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [1.0],
            "close_time": pd.to_datetime(["2025-01-01T04:00:00Z"]),
        }
    )
    lower = pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.0],
            "volume": [1.0],
            "close_time": pd.to_datetime(["2025-01-01T03:45:00Z"]),
        }
    )
    analyzer = MultiTimeframeAnalyzer.production("4h", "15m")

    result = analyzer.analyze(
        higher,
        lower,
        decision_time="2025-01-01T03:45:00Z",
    )

    assert result == {
        "higher_trend": "NEUTRAL",
        "confirmation": "HOLD",
    }
