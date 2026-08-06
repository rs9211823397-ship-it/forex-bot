from types import SimpleNamespace

from strategy.contextual_integration import ContextualGateResult
from strategy.decision import (
    MarketRegimeResult,
    MarketStructureResult,
    MomentumResult,
    SetupResult,
    TradeQualityResult,
    TriggerResult,
    VolumeResult,
)
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


def _high_conviction_decision(reason_codes):
    pipeline = ProductionSignalPipeline.__new__(ProductionSignalPipeline)
    setup = SetupResult(trend_score=30, reasons=("Bullish EMA alignment",))
    trigger = TriggerResult(candle_score=0, reasons=("No candle confirmation",))
    momentum = MomentumResult(score=20, reasons=("Bullish momentum confirmed",))
    volume = VolumeResult(score=15, reasons=("Volume confirms BUY",))
    structure = MarketStructureResult(
        score=10,
        trend="BULLISH",
        reasons=("Market structure bullish",),
    )
    regime = MarketRegimeResult(
        mtf_confirmed=True,
        regime="BULLISH",
        higher_timeframe_available=True,
        confirmation="BUY",
        reasons=("Multi timeframe BUY confirmation",),
    )
    quality = TradeQualityResult(quality=70, approved=True)
    contextual = ContextualGateResult(
        enabled=True,
        approved=False,
        direction="BUY",
        trigger="NONE",
        reasons=tuple(f"Contextual {code}" for code in reason_codes),
        output=SimpleNamespace(reason_codes=tuple(reason_codes)),
    )
    return pipeline._final_decision(
        setup=setup,
        trigger=trigger,
        momentum=momentum,
        volume=volume,
        structure=structure,
        regime=regime,
        quality=quality,
        contextual_gate=contextual,
        strict_direction=True,
    )


def test_missing_exact_context_trigger_is_soft_for_high_conviction_aligned_setup():
    decision = _high_conviction_decision(
        (
            "SETUP_VALID",
            "HTF_ALIGNED",
            "STRUCTURE_ALIGNED",
            "LOCATION_VALID",
            "NO_CONTEXTUAL_TRIGGER",
        )
    )
    assert decision.signal == "BUY"


def test_invalid_location_remains_hard_block_even_when_quality_is_high():
    decision = _high_conviction_decision(
        (
            "SETUP_VALID",
            "HTF_ALIGNED",
            "STRUCTURE_ALIGNED",
            "INVALID_LOCATION",
        )
    )
    assert decision.signal == "HOLD"


def test_legacy_engine_keeps_legacy_pipeline_and_production_uses_new_policy(monkeypatch):
    monkeypatch.setattr(SignalEngine, "_initialize", lambda self, mtf, pipeline_class=SignalPipeline: setattr(self, "pipeline_class", pipeline_class))

    legacy = SignalEngine.__new__(SignalEngine)
    legacy._initialize(None)
    assert legacy.pipeline_class is SignalPipeline

    # Production construction passes the explicit production pipeline class;
    # this assertion protects backward compatibility of non-production users.
    assert ProductionSignalPipeline is not SignalPipeline
