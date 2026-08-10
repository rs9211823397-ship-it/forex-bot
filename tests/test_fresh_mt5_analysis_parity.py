import pandas as pd

from strategy.signal_engine import ProductionSignalPipeline, SignalEngine


def _frame(*, source="MT5", fresh=True):
    frame = pd.DataFrame({"close": [1.0]})
    frame.attrs["source"] = source
    frame.attrs["fresh"] = fresh
    return frame


def test_legacy_engine_delegates_fresh_mt5_analysis_to_production_router(monkeypatch):
    engine = SignalEngine()
    lower = _frame()
    higher = _frame()
    expected = {"signal": "HOLD", "strategy": "TREND", "marker": "production"}

    class FakeProductionEngine:
        pipeline = ProductionSignalPipeline.__new__(ProductionSignalPipeline)

    class FakeRouter:
        def __init__(self, trend_engine, *, higher_timeframe, lower_timeframe):
            assert isinstance(trend_engine, FakeProductionEngine)
            assert higher_timeframe == "1h"
            assert lower_timeframe == "15m"

        def generate_analysis(self, data, symbol, higher_tf):
            assert data is lower
            assert higher_tf is higher
            assert symbol == "EURUSD=X"
            return expected

    monkeypatch.setattr(
        SignalEngine,
        "production",
        classmethod(lambda cls, higher_timeframe, lower_timeframe: FakeProductionEngine()),
    )
    monkeypatch.setattr("strategy.regime_router.RegimeStrategyRouter", FakeRouter)

    assert engine.generate_analysis(lower, "EURUSD=X", higher) is expected


def test_non_mt5_or_stale_frames_keep_legacy_path(monkeypatch):
    engine = SignalEngine()
    called = {"delegated": False}

    def fail_if_delegated(*args, **kwargs):
        called["delegated"] = True
        raise AssertionError("must not delegate")

    monkeypatch.setattr(engine, "_fresh_mt5_production_analysis", fail_if_delegated)
    monkeypatch.setattr(
        engine,
        "generate_signal",
        lambda data, symbol, higher_tf=None: {
            "signal": "HOLD",
            "confidence": 0,
            "score": 0,
            "reasons": [],
            "decision_summary": {"positive": [], "warnings": []},
        },
    )

    engine.generate_analysis(_frame(source="YAHOO"), "EURUSD=X", _frame())
    engine.generate_analysis(_frame(fresh=False), "EURUSD=X", _frame())
    assert called["delegated"] is False
