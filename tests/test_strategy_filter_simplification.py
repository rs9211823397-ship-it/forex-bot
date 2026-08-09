from ai.trade_quality import TradeQuality
from price_action.contextual_trigger import TriggerOutput
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
from strategy.signal_engine import ProductionSignalPipeline


def test_production_allows_quality_approved_setup_without_duplicate_micro_trigger():
    pipeline = ProductionSignalPipeline(trade_quality=TradeQuality())
    contextual_output = TriggerOutput(
        trigger="NONE",
        direction="BUY",
        location="DISCOUNT",
        liquidity_event="NONE",
        candle_quality="NORMAL",
        valid_until=None,
        reason_codes=(
            "NO_CONTEXTUAL_TRIGGER",
            "LOCATION_VALID",
            "HTF_ALIGNED",
            "STRUCTURE_ALIGNED",
        ),
    )
    contextual_gate = ContextualGateResult(
        enabled=True,
        approved=False,
        direction="BUY",
        trigger="NONE",
        reasons=("Contextual Trigger: NONE",),
        output=contextual_output,
    )

    decision = pipeline._final_decision(
        setup=SetupResult(30, ("Bullish EMA alignment",)),
        trigger=TriggerResult(0, reasons=("No candle pattern",)),
        momentum=MomentumResult(0, ("Weak momentum",)),
        volume=VolumeResult(0, ("Weak volume",)),
        structure=MarketStructureResult(
            score=25,
            trend="BULLISH",
            choch="NO CHoCH",
        ),
        regime=MarketRegimeResult(
            mtf_confirmed=True,
            regime="BULLISH",
            higher_timeframe_available=True,
            confirmation="BUY",
        ),
        quality=TradeQualityResult(quality=55, approved=True),
        contextual_gate=contextual_gate,
        strict_direction=True,
    )

    assert decision.signal == "BUY"
    assert decision.score == 55
    assert any("Contextual trigger is soft evidence" in reason for reason in decision.reasons)


def test_production_keeps_wrong_location_as_hard_veto():
    pipeline = ProductionSignalPipeline(trade_quality=TradeQuality())
    contextual_output = TriggerOutput(
        trigger="NONE",
        direction="BUY",
        location="PREMIUM",
        liquidity_event="NONE",
        candle_quality="NORMAL",
        valid_until=None,
        reason_codes=(
            "NO_CONTEXTUAL_TRIGGER",
            "INVALID_LOCATION",
            "HTF_ALIGNED",
            "STRUCTURE_ALIGNED",
        ),
    )
    contextual_gate = ContextualGateResult(
        enabled=True,
        approved=False,
        direction="BUY",
        trigger="NONE",
        reasons=("Contextual INVALID_LOCATION",),
        output=contextual_output,
    )

    decision = pipeline._final_decision(
        setup=SetupResult(30),
        trigger=TriggerResult(0),
        momentum=MomentumResult(0),
        volume=VolumeResult(0),
        structure=MarketStructureResult(
            score=25,
            trend="BULLISH",
            choch="NO CHoCH",
        ),
        regime=MarketRegimeResult(
            mtf_confirmed=True,
            regime="BULLISH",
            higher_timeframe_available=True,
            confirmation="BUY",
        ),
        quality=TradeQualityResult(quality=55, approved=True),
        contextual_gate=contextual_gate,
        strict_direction=True,
    )

    assert decision.signal == "HOLD"
    assert "Rejected: Contextual trigger rejected setup" in decision.reasons
