from types import SimpleNamespace

from price_action.contextual_trigger import TriggerOutput
from strategy.contextual_integration import ContextualProductionAdapter


class StaticTriggerEngine:
    def __init__(self, output):
        self.output = output

    def evaluate(self, context, setup):
        return self.output


def test_contextual_rejection_exposes_location_liquidity_and_candle_quality():
    output = TriggerOutput(
        trigger="NONE",
        direction="BUY",
        location="PREMIUM",
        liquidity_event="NONE",
        candle_quality="NONE",
        valid_until=None,
        reason_codes=("INVALID_LOCATION",),
    )
    adapter = ContextualProductionAdapter(
        trigger_engine=StaticTriggerEngine(output)
    )
    setup = SimpleNamespace(direction="BUY")

    result = adapter.evaluate_trigger(object(), setup)

    assert result.approved is False
    assert "Contextual Trigger: NONE" in result.reasons
    assert "Contextual Location: PREMIUM" in result.reasons
    assert "Contextual Liquidity: NONE" in result.reasons
    assert "Contextual Candle Quality: NONE" in result.reasons
    assert "Contextual INVALID_LOCATION" in result.reasons
