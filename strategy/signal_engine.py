import logging
from dataclasses import replace

from structure.market_structure import MarketStructure
from price_action.candles import CandlePatterns
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from ai.trade_quality import TradeQuality
from ai.decision_analyzer import AIDecisionAnalyzer
from strategy.pipeline import SignalPipeline
from strategy.setup_detector import SetupDetector
from strategy.trigger_detector import TriggerDetector


logger = logging.getLogger(__name__)


class ProductionSignalPipeline(SignalPipeline):
    """Production policy with non-duplicated hard gates.

    Structure and higher-timeframe direction are hard safety gates. Momentum,
    legacy candle confirmation, and contextual trigger evidence contribute to
    ranking/quality without each receiving an independent veto.

    Context remains fail-closed for wrong HTF/structure/location. The only
    contextual case allowed to become soft evidence is a fully aligned setup in
    a valid location where the *only* missing item is an exact contextual candle
    trigger and the setup is already high-conviction by independent evidence.
    This prevents a good trend setup being rejected twice for the same missing
    micro-trigger while still refusing premium BUYs / discount SELLs.
    """

    HIGH_CONVICTION_QUALITY = 65
    HIGH_CONVICTION_SCORE_BUFFER = 10

    @staticmethod
    def _eligibility_failures(
        direction,
        trigger,
        momentum,
        structure,
        regime,
        contextual_gate,
    ):
        failures = []

        if direction is None:
            return ("No directional setup",)

        if not structure.allows(direction):
            failures.append("Market structure conflicts with setup")

        if not regime.allows(direction):
            failures.append("Higher timeframe conflicts with setup")

        if (
            contextual_gate.enabled
            and (
                not contextual_gate.approved
                or contextual_gate.direction != direction
            )
        ):
            failures.append("Contextual trigger rejected setup")

        return tuple(failures)

    def _final_decision(
        self,
        setup,
        trigger,
        momentum,
        volume,
        structure,
        regime,
        quality,
        contextual_gate,
        strict_direction=False,
    ):
        """Apply a narrowly-scoped soft-trigger policy for strong aligned setups."""

        direction = setup.direction
        directional_score = (
            setup.trend_score
            + momentum.score
            + trigger.candle_score
            + volume.score
            + structure.score
        )
        required_score = self.BUY_THRESHOLD + self.HIGH_CONVICTION_SCORE_BUFFER

        output = getattr(contextual_gate, "output", None)
        reason_codes = set(getattr(output, "reason_codes", ()) or ())
        missing_trigger_only = (
            "NO_CONTEXTUAL_TRIGGER" in reason_codes
            and "LOCATION_VALID" in reason_codes
            and "HTF_ALIGNED" in reason_codes
            and "STRUCTURE_ALIGNED" in reason_codes
            and not {
                "INVALID_LOCATION",
                "HTF_DIRECTION_MISMATCH",
                "STRUCTURE_DIRECTION_MISMATCH",
                "SETUP_EXPIRED",
                "SETUP_NOT_ACTIVE",
            }.intersection(reason_codes)
        )
        high_conviction = (
            direction in {"BUY", "SELL"}
            and quality.approved
            and quality.quality >= self.HIGH_CONVICTION_QUALITY
            and abs(directional_score) >= required_score
            and structure.allows(direction)
            and regime.allows(direction)
        )

        effective_contextual_gate = contextual_gate
        if (
            contextual_gate.enabled
            and not contextual_gate.approved
            and contextual_gate.direction == direction
            and missing_trigger_only
            and high_conviction
        ):
            effective_contextual_gate = replace(
                contextual_gate,
                enabled=False,
                approved=True,
                reasons=contextual_gate.reasons
                + (
                    "Contextual trigger is soft evidence: high-conviction setup "
                    "already has aligned HTF, structure, and valid location",
                ),
            )

        return super()._final_decision(
            setup=setup,
            trigger=trigger,
            momentum=momentum,
            volume=volume,
            structure=structure,
            regime=regime,
            quality=quality,
            contextual_gate=effective_contextual_gate,
            strict_direction=strict_direction,
        )


class SignalEngine:

    def __init__(self):
        self._initialize(MultiTimeframeAnalyzer(), SignalPipeline)

    def _initialize(self, mtf, pipeline_class=SignalPipeline):
        self.market_structure = MarketStructure()
        self.candles = CandlePatterns()
        self.mtf = mtf
        self.trade_quality = TradeQuality()
        self.decision_analyzer = AIDecisionAnalyzer()
        self.setup_detector = SetupDetector()
        self.trigger_detector = TriggerDetector(self.candles)
        self.pipeline = pipeline_class(
            market_structure=self.market_structure,
            candles=self.candles,
            mtf=self.mtf,
            trade_quality=self.trade_quality,
            setup_detector=self.setup_detector,
            trigger_detector=self.trigger_detector
        )

    @classmethod
    def production(cls, higher_timeframe, lower_timeframe):
        """Construct a timestamp-required production signal engine."""

        engine = cls.__new__(cls)
        engine._initialize(
            MultiTimeframeAnalyzer.production(
                higher_timeframe=higher_timeframe,
                lower_timeframe=lower_timeframe,
            ),
            ProductionSignalPipeline,
        )
        return engine

    def generate_signal(self, data, symbol, higher_tf=None):
        """Return the stable strategy dictionary contract."""

        return self.pipeline.run(
            data,
            symbol,
            higher_tf
        ).to_dict()

    def generate_analysis(self, data, symbol, higher_tf=None):
        """Return the strategy decision plus an explainable AI report."""

        result = self.generate_signal(data, symbol, higher_tf)

        summary = result.get("decision_summary", {})
        report = self.decision_analyzer.analyze(
            signal=result["signal"],
            confidence=result["confidence"],
            score=result["score"],
            reasons=result.get("reasons", []),
            decision_summary=summary,
        )
        report["report_text"] = self.decision_analyzer.format_report(report)
        result["decision_report"] = report

        if result.get("signal") == "HOLD":
            reasons = tuple(str(item) for item in result.get("reasons", ()) if item)
            warnings = tuple(
                str(item)
                for item in summary.get("warnings", ())
                if item
            ) if isinstance(summary, dict) else ()
            logger.info(
                "HOLD detail %s | score=%s | reasons=%s | warnings=%s",
                symbol,
                result.get("score"),
                "; ".join(reasons) or "none",
                "; ".join(warnings) or "none",
            )

        return result
