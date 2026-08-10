import logging
from dataclasses import replace

from structure.market_structure import MarketStructure
from price_action.candles import CandlePatterns
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from ai.trade_quality import TradeQuality
from ai.decision_analyzer import AIDecisionAnalyzer
from strategy.pipeline import SignalPipeline
from strategy.decision import MomentumResult
from strategy.setup_detector import SetupDetector
from strategy.trigger_detector import TriggerDetector
from config.settings import MIN_TRADE_QUALITY


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

    HIGH_CONVICTION_QUALITY = MIN_TRADE_QUALITY
    HIGH_CONVICTION_SCORE_BUFFER = 0

    def _confirm_momentum(self, latest):
        """Use RSI only as an extreme veto; MACD already votes in the setup."""
        rsi = float(latest["RSI"])
        if rsi >= 75.0:
            return MomentumResult(
                score=-20,
                reasons=("RSI extreme overbought: blocks new BUY entries",),
            )
        if rsi <= 25.0:
            return MomentumResult(
                score=20,
                reasons=("RSI extreme oversold: blocks new SELL entries",),
            )
        return MomentumResult(
            score=0,
            reasons=("RSI is not at an opposing extreme",),
        )

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

        momentum_score = int(getattr(momentum, "score", 0))
        if (direction == "BUY" and momentum_score < 0) or (
            direction == "SELL" and momentum_score > 0
        ):
            failures.append("RSI extreme conflicts with setup")

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
        latest=None,
    ):
        """Soften only a duplicated micro-trigger veto on approved aligned setups."""

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
        contextual_caution_only = (
            "SETUP_VALID" in reason_codes
            and "HTF_ALIGNED" in reason_codes
            and "STRUCTURE_ALIGNED" in reason_codes
            and {
                "NO_CONTEXTUAL_TRIGGER",
                "INVALID_LOCATION",
            }.intersection(reason_codes)
            and not {
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

        structural_trigger = (
            direction == "BUY"
            and structure.bos == "BULLISH BOS"
        ) or (
            direction == "SELL"
            and structure.bos == "BEARISH BOS"
        ) or (
            direction == "BUY"
            and structure.choch == "BULLISH CHoCH"
        ) or (
            direction == "SELL"
            and structure.choch == "BEARISH CHoCH"
        )
        aligned_majority = (
            direction in {"BUY", "SELL"}
            and abs(setup.trend_score) >= 20
            and structure.allows(direction)
            and regime.allows(direction)
        )

        effective_contextual_gate = contextual_gate
        if (
            contextual_gate.enabled
            and not contextual_gate.approved
            and contextual_gate.direction == direction
            and contextual_caution_only
            and (high_conviction or aligned_majority)
        ):
            effective_contextual_gate = replace(
                contextual_gate,
                enabled=False,
                approved=True,
                reasons=contextual_gate.reasons
                + (
                    "Contextual trigger/location is soft evidence: majority setup "
                    "already has aligned HTF and structure",
                ),
            )

        if structural_trigger and aligned_majority:
            effective_contextual_gate = replace(
                contextual_gate,
                enabled=False,
                approved=True,
                reasons=contextual_gate.reasons
                + ("BOS/CHoCH is the directional entry trigger",),
            )

        effective_trigger = trigger
        if structural_trigger and aligned_majority:
            structural_score = 10 if direction == "BUY" else -10
            if abs(trigger.candle_score) < 10:
                effective_trigger = replace(
                    trigger,
                    candle_score=structural_score,
                    reasons=trigger.reasons
                    + ("BOS/CHoCH supplies the entry trigger",),
                )

        decision = super()._final_decision(
            setup=setup,
            trigger=effective_trigger,
            momentum=momentum,
            volume=volume,
            structure=structure,
            regime=regime,
            quality=quality,
            contextual_gate=effective_contextual_gate,
            strict_direction=strict_direction,
        )

        if decision.signal not in {"BUY", "SELL"} or latest is None:
            return decision

        rsi = float(latest["RSI"])
        close = float(latest["close"])
        upper = float(latest["BB_UPPER"])
        lower = float(latest["BB_LOWER"])
        extreme_against = (
            decision.signal == "BUY"
            and (rsi >= 75.0 or (close >= upper and rsi >= 70.0))
        ) or (
            decision.signal == "SELL"
            and (rsi <= 25.0 or (close <= lower and rsi <= 30.0))
        )
        if not extreme_against:
            return decision

        return replace(
            decision,
            signal="HOLD",
            reasons=decision.reasons
            + ("Rejected: RSI/Bollinger extreme conflicts with entry",),
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
        self.setup_detector = SetupDetector(
            allow_momentum_fallback=(pipeline_class is ProductionSignalPipeline)
        )
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

    @staticmethod
    def _fresh_mt5_frame(frame):
        attrs = getattr(frame, "attrs", {}) or {}
        return bool(
            frame is not None
            and attrs.get("source") == "MT5"
            and attrs.get("fresh") is True
        )

    def _should_delegate_fresh_mt5_analysis(self, data, higher_tf):
        return bool(
            not isinstance(self.pipeline, ProductionSignalPipeline)
            and self._fresh_mt5_frame(data)
            and self._fresh_mt5_frame(higher_tf)
        )

    def _fresh_mt5_production_analysis(self, data, symbol, higher_tf):
        """Keep broker-native analysis identical to the trading engine policy.

        Telegram historically constructed ``SignalEngine()`` directly, which
        selected the legacy research pipeline even while market data came from
        the live MT5 demo feed.  Fresh broker-native frames are now routed to
        the same production signal engine and regime router used by
        ``TradingApplication``.  Synthetic, cached, Yahoo and legacy research
        calls continue using the compatibility pipeline.
        """
        from config.settings import HIGHER_TIMEFRAME, TRADING_TIMEFRAME
        from strategy.regime_router import RegimeStrategyRouter

        production_engine = SignalEngine.production(
            higher_timeframe=HIGHER_TIMEFRAME,
            lower_timeframe=TRADING_TIMEFRAME,
        )
        router = RegimeStrategyRouter(
            production_engine,
            higher_timeframe=HIGHER_TIMEFRAME,
            lower_timeframe=TRADING_TIMEFRAME,
        )
        return router.generate_analysis(data, symbol, higher_tf)

    def generate_signal(self, data, symbol, higher_tf=None):
        """Return the stable strategy dictionary contract."""

        return self.pipeline.run(
            data,
            symbol,
            higher_tf
        ).to_dict()

    def generate_analysis(self, data, symbol, higher_tf=None):
        """Return the strategy decision plus an explainable AI report."""

        if self._should_delegate_fresh_mt5_analysis(data, higher_tf):
            return self._fresh_mt5_production_analysis(data, symbol, higher_tf)

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
