from __future__ import annotations

import json
from pathlib import Path

from ai.chart_analysis.analytics import OutcomeAnalytics
from ai.chart_analysis.config import ChartObserverConfig


def _write_record(
    root: Path,
    *,
    snapshot_id: str,
    symbol: str,
    signal: str,
    confidence: int,
    regime: str,
    strategy: str,
    outcome: dict | None,
) -> None:
    directory = root / "2026-08-12" / snapshot_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "input.json").write_text(
        json.dumps(
            {
                "snapshot": {
                    "snapshot_id": snapshot_id,
                    "symbol": symbol,
                    "as_of_utc": "2026-08-12T00:00:00+00:00",
                },
                "deterministic_comparison": {
                    "signal": signal,
                    "confidence": confidence,
                    "regime": regime,
                    "strategy": strategy,
                },
            }
        ),
        encoding="utf-8",
    )
    if outcome is not None:
        (directory / "outcome.json").write_text(json.dumps(outcome), encoding="utf-8")


def _outcome(*, realized_r: float | None, status: str, mtm: float) -> dict:
    return {
        "record_type": "AAQTS_CHART_OUTCOME",
        "finalized": True,
        "available_future_bars": 12,
        "final": {"status": status, "realized_r": realized_r},
        "horizons": {
            "1": {
                "mark_to_market_r": mtm,
                "mfe_r": max(mtm, 0.2),
                "mae_r": 0.25,
                "first_barrier_event": "TP" if status == "TP" else "SL" if status == "SL" else None,
            },
            "3": {
                "mark_to_market_r": mtm,
                "mfe_r": max(mtm, 0.3),
                "mae_r": 0.3,
                "first_barrier_event": None,
            },
            "6": {
                "mark_to_market_r": mtm,
                "mfe_r": max(mtm, 0.4),
                "mae_r": 0.35,
                "first_barrier_event": None,
            },
            "12": {
                "mark_to_market_r": mtm,
                "mfe_r": max(mtm, 0.5),
                "mae_r": 0.4,
                "first_barrier_event": "TP" if status == "TP" else "SL" if status == "SL" else None,
            },
        },
    }


def test_analytics_builds_final_and_bucket_metrics(tmp_path):
    _write_record(
        tmp_path,
        snapshot_id="gbp-buy",
        symbol="GBPUSD=X",
        signal="BUY",
        confidence=56,
        regime="TREND_UP",
        strategy="TREND",
        outcome=_outcome(realized_r=2.0, status="TP", mtm=1.4),
    )
    _write_record(
        tmp_path,
        snapshot_id="nzd-sell",
        symbol="NZDUSD=X",
        signal="SELL",
        confidence=44,
        regime="TREND_DOWN",
        strategy="TREND",
        outcome=_outcome(realized_r=-1.0, status="SL", mtm=-0.8),
    )
    _write_record(
        tmp_path,
        snapshot_id="eur-pending",
        symbol="EURUSD=X",
        signal="BUY",
        confidence=63,
        regime="RANGE",
        strategy="BREAKOUT",
        outcome=None,
    )

    config = ChartObserverConfig(
        output_root=tmp_path,
        analytics_min_finalized_samples=30,
        analytics_min_bucket_samples=10,
    )
    summary = OutcomeAnalytics(config).refresh()

    assert summary["counts"] == {
        "captures": 3,
        "pending": 1,
        "finalized": 2,
        "errors": 0,
    }
    assert summary["overall"]["expectancy_r"] == 0.5
    assert summary["overall"]["profit_factor"] == 2.0
    assert summary["overall"]["positive_r_rate"] == 0.5
    assert summary["horizons"]["1"]["samples"] == 2
    assert summary["horizons"]["1"]["avg_mark_to_market_r"] == 0.3
    assert summary["by_symbol"]["GBPUSD=X"]["final"]["samples"] == 1
    assert summary["by_signal"]["SELL"]["final"]["samples"] == 1
    assert summary["by_confidence"]["50_59"]["captures"] == 1
    assert summary["by_regime"]["TREND_UP"]["captures"] == 1
    assert summary["by_strategy"]["TREND"]["captures"] == 2
    assert summary["readiness"]["ready_for_overall_conclusions"] is False
    assert summary["by_symbol"]["GBPUSD=X"]["sample_guardrail_met"] is False
    assert (tmp_path / "analytics_summary.json").exists()


def test_analytics_never_writes_infinity_when_only_winners_exist(tmp_path):
    _write_record(
        tmp_path,
        snapshot_id="winner",
        symbol="EURUSD=X",
        signal="BUY",
        confidence=72,
        regime="TREND_UP",
        strategy="TREND",
        outcome=_outcome(realized_r=2.0, status="TP", mtm=2.0),
    )
    config = ChartObserverConfig(output_root=tmp_path)
    analytics = OutcomeAnalytics(config)
    summary = analytics.refresh()

    assert summary["overall"]["profit_factor"] is None
    persisted = json.loads((tmp_path / "analytics_summary.json").read_text(encoding="utf-8"))
    assert persisted["overall"]["profit_factor"] is None


def test_analytics_marks_guardrails_ready_only_after_minimum_samples(tmp_path):
    for index in range(3):
        _write_record(
            tmp_path,
            snapshot_id=f"sample-{index}",
            symbol="EURUSD=X",
            signal="BUY",
            confidence=55,
            regime="TREND_UP",
            strategy="TREND",
            outcome=_outcome(realized_r=0.5, status="TIME_HORIZON", mtm=0.5),
        )

    config = ChartObserverConfig(
        output_root=tmp_path,
        analytics_min_finalized_samples=3,
        analytics_min_bucket_samples=3,
    )
    summary = OutcomeAnalytics(config).refresh()

    assert summary["readiness"]["ready_for_overall_conclusions"] is True
    assert summary["by_symbol"]["EURUSD=X"]["sample_guardrail_met"] is True
    assert summary["by_confidence"]["50_59"]["sample_guardrail_met"] is True
