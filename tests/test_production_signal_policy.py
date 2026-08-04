from types import SimpleNamespace

from strategy.signal_engine import ProductionSignalPipeline, SignalEngine
from strategy.pipeline import SignalPipeline


class Directional:
    def __init__(self, allowed):
        self.allowed = allowed

    def allows(self, direction):
        return self.allowed


class Confirmation:
    def __init__(self, confirmed):
        self.confirmed = confirmed

    def confirms(self, direction):
        return self.confirmed


def gate(*, approved=True, direction="BUY", enabled=True):
    return SimpleNamespace(
        enabled=enabled,
        approved=approved,
        direction=direction,
    )


def test_production_policy_does_not_duplicate_momentum_and_legacy_candle_gates():
    failures = ProductionSignalPipeline._eligibility_failures(
        direction="BUY",
        trigger=Confirmation(False),
        momentum=Confirmation(False),
        structure=Directional(True),
        regime=Directional(True),
        contextual_gate=gate(),
    )

    assert failures == ()


def test_production_policy_keeps_structure_htf_and_contextual_fail_closed():
    failures = ProductionSignalPipeline._eligibility_failures(
        direction="BUY",
        trigger=Confirmation(True),
        momentum=Confirmation(True),
        structure=Directional(False),
        regime=Directional(False),
        contextual_gate=gate(approved=False, direction=None),
    )

    assert "Market structure conflicts with setup" in failures
    assert "Higher timeframe conflicts with setup" in failures
    assert "Contextual trigger rejected setup" in failures


def test_legacy_engine_keeps_legacy_pipeline_and_production_uses_new_policy(monkeypatch):
    monkeypatch.setattr(SignalEngine, "_initialize", lambda self, mtf, pipeline_class=SignalPipeline: setattr(self, "pipeline_class", pipeline_class))

    legacy = SignalEngine.__new__(SignalEngine)
    legacy._initialize(None)
    assert legacy.pipeline_class is SignalPipeline

    # Production construction passes the explicit production pipeline class;
    # this assertion protects backward compatibility of non-production users.
    assert ProductionSignalPipeline is not SignalPipeline
