from __future__ import annotations

from pathlib import Path

import pandas as pd

import ai.chart_analysis.integration as integration
from strategy.regime_router import RegimeStrategyRouter


def test_integration_is_lazy_when_disabled(monkeypatch):
    monkeypatch.setenv("AAQTS_AI_CHART_ENABLED", "false")
    monkeypatch.setattr(integration, "_observer", None)

    scheduled = integration.observe_routed_decision(
        symbol="EURUSD=X",
        lower_frame=pd.DataFrame(),
        higher_frame=pd.DataFrame(),
        deterministic={"signal": "BUY"},
        lower_timeframe="15m",
        higher_timeframe="1h",
    )

    assert scheduled is False
    assert integration._observer is None


def test_integration_failure_is_fail_open(monkeypatch):
    class ExplodingObserver:
        def observe(self, **kwargs):
            raise RuntimeError("synthetic observer failure")

        def status(self):
            return {"enabled": True}

    monkeypatch.setenv("AAQTS_AI_CHART_ENABLED", "true")
    monkeypatch.setattr(integration, "_observer", ExplodingObserver())

    scheduled = integration.observe_routed_decision(
        symbol="EURUSD=X",
        lower_frame=pd.DataFrame({"close_time": [pd.Timestamp("2026-08-12T00:15:00Z")]}),
        higher_frame=pd.DataFrame({"close_time": [pd.Timestamp("2026-08-12T00:00:00Z")]}),
        deterministic={"signal": "BUY"},
        lower_timeframe="15m",
        higher_timeframe="1h",
    )

    assert scheduled is False


def test_router_observer_return_value_cannot_change_decision(monkeypatch):
    routed = {
        "signal": "BUY",
        "confidence": 61,
        "strategy": "TREND",
        "regime": "TREND_UP",
        "reasons": ["synthetic deterministic decision"],
    }
    captured = {}

    def fake_observe(**kwargs):
        captured.update(kwargs)
        return False

    monkeypatch.setattr("strategy.regime_router.observe_routed_decision", fake_observe)

    router = object.__new__(RegimeStrategyRouter)
    router.lower_timeframe = "15m"
    router.higher_timeframe = "1h"
    router._generate_analysis = lambda data, symbol, higher_tf=None: routed

    lower = object()
    higher = object()
    result = RegimeStrategyRouter.generate_analysis(router, lower, "EURUSD=X", higher)

    assert result is routed
    assert result["signal"] == "BUY"
    assert captured["symbol"] == "EURUSD=X"
    assert captured["lower_frame"] is lower
    assert captured["higher_frame"] is higher
    assert captured["deterministic"] is routed


def test_windows_launcher_uses_capture_only_observer_mode():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "scripts" / "windows" / "start-demo-engine.ps1").read_text(
        encoding="utf-8"
    )
    setter = (root / "scripts" / "windows" / "set-openai-api-key.ps1").read_text(
        encoding="utf-8"
    )

    assert "openai_api_key.dpapi" in launcher
    assert 'AAQTS_AI_CHART_MODE = "OBSERVER"' in launcher
    assert 'AAQTS_AI_CHART_ONLY_ACTIONABLE = "true"' in launcher
    assert 'AAQTS_AI_CHART_ENABLED = "true"' in launcher
    assert 'AAQTS_AI_CHART_REMOTE_ENABLED = "false"' in launcher
    assert 'AAQTS_AI_CHART_OUTCOMES_ENABLED = "true"' in launcher
    assert 'AAQTS_AI_CHART_OUTCOME_HORIZONS = "1,3,6,12"' in launcher
    assert 'AAQTS_AI_CHART_ANALYTICS_ENABLED = "true"' in launcher
    assert 'AAQTS_AI_CHART_ANALYTICS_MIN_FINALIZED = "30"' in launcher
    assert 'AAQTS_AI_CHART_ANALYTICS_MIN_BUCKET = "10"' in launcher
    assert "Remove-Item Env:OPENAI_API_KEY" in launcher
    assert "ConvertTo-SecureString" in launcher
    assert "ConvertFrom-SecureString" in setter
    assert "Read-Host" in setter
    assert "-AsSecureString" in setter
