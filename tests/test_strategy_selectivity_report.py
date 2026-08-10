import pandas as pd
import pytest

from scripts.strategy_selectivity_report import AUDIT_POLICY, _scope, _summary


def test_selectivity_replay_freezes_the_documented_demo_policy():
    assert AUDIT_POLICY == {
        "min_adx": 12.0,
        "signal_score_threshold": 35,
        "min_signal_confirmations": 1,
        "min_trade_quality": 35,
        "min_regime_confidence": 35.0,
    }


def test_scope_discloses_single_synthetic_symbol_and_elapsed_span():
    frame = pd.DataFrame(
        {
            "close_time": pd.date_range(
                "2026-01-01T00:15:00Z",
                periods=3,
                freq="15min",
            )
        }
    )

    scope = _scope(frame, [0, 1, 2])

    assert scope["source"] == "deterministic_synthetic_mixed_regime"
    assert scope["symbols"] == ["ETH-USD"]
    assert scope["symbol_count"] == 1
    assert scope["elapsed_hours"] == 0.5
    assert "not broker orders" in scope["frequency_warning"]


def test_scope_rejects_an_empty_decision_set():
    with pytest.raises(ValueError, match="at least one"):
        _scope(pd.DataFrame({"close_time": []}), [])


def test_summary_distinguishes_actions_from_candidates():
    results = [
        {
            "signal": "BUY",
            "decision_report": {"candidate_direction": "BUY"},
        },
        {
            "signal": "HOLD",
            "strategy": "NO_TRADE",
            "decision_report": {"candidate_direction": "SELL"},
        },
    ]

    summary = _summary(results)

    assert summary["action_rate_percent"] == 50.0
    assert summary["hold_rate_percent"] == 50.0
    assert summary["candidate_acceptance_percent"] == 50.0
