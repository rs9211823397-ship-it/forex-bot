from structure.market_structure import MarketStructure
from price_action.candles import CandlePatterns
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from ai.trade_quality import TradeQuality
from ai.decision_analyzer import AIDecisionAnalyzer
from strategy.pipeline import SignalPipeline
from strategy.setup_detector import SetupDetector
from strategy.trigger_detector import TriggerDetector


class SignalEngine:

    def __init__(self):
        self._initialize(MultiTimeframeAnalyzer())

    def _initialize(self, mtf):
        self.market_structure = MarketStructure()
        self.candles = CandlePatterns()
        self.mtf = mtf
        self.trade_quality = TradeQuality()
        self.decision_analyzer = AIDecisionAnalyzer()
        self.setup_detector = SetupDetector()
        self.trigger_detector = TriggerDetector(self.candles)
        self.pipeline = SignalPipeline(
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
            )
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
