from types import SimpleNamespace

import pandas as pd

from price_action.contextual_trigger import ContextualTriggerEngine, SetupContext
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


def _high_conviction_decision(reason_codes, *, quality=70, latest=None):
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
    quality = TradeQualityResult(quality=quality, approved=quality >= 55)
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
        latest=latest,
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


def test_invalid_location_is_soft_when_majority_htf_and_structure_align():
    decision = _high_conviction_decision(
        (
            "SETUP_VALID",
            "HTF_ALIGNED",
            "STRUCTURE_ALIGNED",
            "INVALID_LOCATION",
        )
    )
    assert decision.signal == "BUY"
    assert any(
        "Contextual trigger/location is soft evidence" in reason
        for reason in decision.reasons
    )


def test_real_contextual_output_softens_invalid_location_after_true_alignment():
    now = pd.Timestamp("2026-08-10T06:00:00Z")

    class InvalidZone:
        location = "PREMIUM"

        @staticmethod
        def valid_for_direction(_direction):
            return False

    context = SimpleNamespace(
        decision_time=now,
        htf_regime=SimpleNamespace(regime="BULLISH"),
        structure=SimpleNamespace(trend="BULLISH"),
        zones=InvalidZone(),
        liquidity=SimpleNamespace(event="NONE"),
    )
    output = ContextualTriggerEngine().evaluate(
        context,
        SetupContext(
            direction="BUY",
            created_at=now,
            valid_until=now + pd.Timedelta(minutes=45),
        ),
    )

    decision = _high_conviction_decision(output.reason_codes)

    assert output.reason_codes == (
        "SETUP_VALID",
        "HTF_ALIGNED",
        "STRUCTURE_ALIGNED",
        "INVALID_LOCATION",
    )
    assert decision.signal == "BUY"


def test_contextual_htf_mismatch_remains_hard_block():
    decision = _high_conviction_decision(
        (
            "SETUP_VALID",
            "HTF_ALIGNED",
            "STRUCTURE_ALIGNED",
            "INVALID_LOCATION",
            "HTF_DIRECTION_MISMATCH",
        )
    )
    assert decision.signal == "HOLD"


def test_neutral_htf_softens_duplicate_context_gate_only_for_high_conviction():
    reason_codes = (
        "SETUP_VALID",
        "HTF_NEUTRAL",
        "STRUCTURE_ALIGNED",
        "LOCATION_VALID",
        "NO_CONTEXTUAL_TRIGGER",
    )

    assert _high_conviction_decision(reason_codes).signal == "BUY"
    assert _high_conviction_decision(reason_codes, quality=40).signal == "HOLD"


def test_bos_is_entry_trigger_without_duplicate_contextual_veto():
    pipeline = ProductionSignalPipeline.__new__(ProductionSignalPipeline)
    decision = pipeline._final_decision(
        setup=SetupResult(25, ("Bullish majority trend vote (2/3)",)),
        trigger=TriggerResult(0, reasons=("No candle confirmation",)),
        momentum=MomentumResult(0, ("RSI is not at an opposing extreme",)),
        volume=VolumeResult(0),
        structure=MarketStructureResult(
            score=20,
            trend="BULLISH",
            bos="BULLISH BOS",
        ),
        regime=MarketRegimeResult(
            mtf_confirmed=False,
            regime="BULLISH",
            higher_timeframe_available=True,
            confirmation="HOLD",
        ),
        quality=TradeQualityResult(quality=55, approved=True),
        contextual_gate=ContextualGateResult(
            enabled=True,
            approved=False,
            direction="BUY",
            trigger="NONE",
            reasons=("Contextual INVALID_LOCATION",),
            output=SimpleNamespace(reason_codes=("INVALID_LOCATION",)),
        ),
        strict_direction=True,
    )

    assert decision.signal == "BUY"
    assert "BOS/CHoCH is the directional entry trigger" in decision.reasons


def test_rsi_extreme_remains_hard_veto():
    failures = ProductionSignalPipeline._eligibility_failures(
        direction="BUY",
        trigger=Confirmation(False),
        momentum=MomentumResult(score=-20),
        structure=Directional(True),
        regime=Directional(True),
        contextual_gate=gate(enabled=False),
    )

    assert "RSI extreme conflicts with setup" in failures


def test_rsi_is_never_a_standalone_veto_without_price_reversal():
    pipeline = ProductionSignalPipeline.__new__(ProductionSignalPipeline)

    normal = pipeline._confirm_momentum({"RSI": 76.0})
    exhausted = pipeline._confirm_momentum({"RSI": 83.0})

    assert normal.score == 0
    assert exhausted.score == 0


def test_rsi_bollinger_veto_requires_opposing_reversal_candle():
    reason_codes = (
        "SETUP_VALID",
        "HTF_ALIGNED",
        "STRUCTURE_ALIGNED",
        "LOCATION_VALID",
        "NO_CONTEXTUAL_TRIGGER",
    )
    continuation = {
        "RSI": 85.0,
        "open": 99.0,
        "close": 101.0,
        "BB_UPPER": 100.0,
        "BB_LOWER": 90.0,
    }
    reversal = dict(continuation, open=102.0, close=101.0)

    assert _high_conviction_decision(reason_codes, latest=continuation).signal == "BUY"
    blocked = _high_conviction_decision(reason_codes, latest=reversal)
    assert blocked.signal == "HOLD"
    assert any(
        "RSI/Bollinger extreme has an opposing reversal candle" in reason
        for reason in blocked.reasons
    )


def test_legacy_engine_keeps_legacy_pipeline_and_production_uses_new_policy(monkeypatch):
    monkeypatch.setattr(SignalEngine, "_initialize", lambda self, mtf, pipeline_class=SignalPipeline: setattr(self, "pipeline_class", pipeline_class))

    legacy = SignalEngine.__new__(SignalEngine)
    legacy._initialize(None)
    assert legacy.pipeline_class is SignalPipeline

    # Production construction passes the explicit production pipeline class;
    # this assertion protects backward compatibility of non-production users.
    assert ProductionSignalPipeline is not SignalPipeline
