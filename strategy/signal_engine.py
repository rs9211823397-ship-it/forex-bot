from structure.market_structure import MarketStructure
from price_action.candles import CandlePatterns
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from ai.trade_quality import TradeQuality
from ai.decision_analyzer import AIDecisionAnalyzer
from strategy.pipeline import SignalPipeline
from strategy.setup_detector import SetupDetector
from strategy.trigger_detector import TriggerDetector


class ProductionSignalPipeline(SignalPipeline):
    """Production policy with non-duplicated hard gates.

    The causal contextual trigger is the production price-action gate. Legacy
    candle and momentum confirmations remain part of score/trade-quality, but
    are not independently required a second time after those stages have
    already contributed to the decision. Structure, HTF direction, and the
    causal contextual trigger remain fail-closed hard requirements.
    """

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
        return result
