"""Deterministic, compatibility-preserving strategy decision pipeline."""

from ai.trade_quality import TradeQuality
from price_action.candles import CandlePatterns
from strategy.contextual_integration import (
    ContextualGateResult,
    ContextualProductionAdapter,
    prepare_causal_market_data
)
from strategy.decision import (
    DecisionSummary,
    MarketRegimeResult,
    MarketStructureResult,
    MomentumResult,
    SignalDecision,
    TradeQualityResult,
    VolumeResult
)
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from strategy.setup_detector import SetupDetector
from strategy.trigger_detector import TriggerDetector
from strategy.validators import (
    validate_data,
    validate_input_frame,
    validate_market_regime,
    validate_risk,
    validate_strategy_features
)
from structure.market_structure import MarketStructure


class SignalPipeline:
    """Run the legacy strategy through explicit, ordered stages."""

    BUY_THRESHOLD = 55
    SELL_THRESHOLD = -55
    MIN_CONFIRMATIONS = 3


    STAGE_ORDER = (
        "data_validation",
        "market_regime",
        "market_structure",
        "setup_detection",
        "context_builder",
        "contextual_trigger",
        "momentum_confirmation",
        "trade_quality",
        "risk_validation",
        "final_decision"
    )

    def __init__(
        self,
        market_structure=None,
        candles=None,
        mtf=None,
        trade_quality=None,
        setup_detector=None,
        trigger_detector=None,
        contextual_adapter=None
    ):
        self.market_structure = market_structure or MarketStructure()
        self.candles = candles or CandlePatterns()
        self.mtf = mtf or MultiTimeframeAnalyzer()
        self.trade_quality = trade_quality or TradeQuality()
        self.setup_detector = setup_detector or SetupDetector()
        self.trigger_detector = (
            trigger_detector or TriggerDetector(self.candles)
        )
        self.contextual_adapter = (
            contextual_adapter
            or ContextualProductionAdapter()
        )
        self.last_context = None
        self.last_contextual_trigger = None
        self._last_stage_order = ()

    @property
    def last_stage_order(self):
        return self._last_stage_order

    def _record(self, trace, stage):
        trace.append(stage)
        self._last_stage_order = tuple(trace)

    def _evaluate_regime(
        self,
        higher_tf,
        data,
        confirmed_at=None
    ):
        mtf_confirmed = True
        reasons = []
        regime = "NEUTRAL"
        confirmation = "HOLD"

        if higher_tf is not None:
            mtf_result = self.mtf.analyze(
                higher_tf,
                data
            )
            higher_trend = mtf_result.get(
                "higher_trend",
                "SIDEWAYS"
            )
            confirmation = mtf_result.get(
                "confirmation",
                "HOLD"
            )

            if higher_trend in {"BULLISH", "BEARISH"}:
                regime = higher_trend

            if confirmation == "BUY":
                mtf_confirmed = True
                reasons.append(
                    "Multi timeframe BUY confirmation"
                )

            elif confirmation == "SELL":
                mtf_confirmed = True
                reasons.append(
                    "Multi timeframe SELL confirmation"
                )

            else:
                mtf_confirmed = False
                reasons.append(
                    "Multi timeframe rejected"
                )

        return MarketRegimeResult(
            mtf_confirmed=mtf_confirmed,
            reasons=tuple(reasons),
            regime=regime,
            confirmed_at=confirmed_at,
            higher_timeframe_available=(
                higher_tf is not None
            ),
            confirmation=confirmation
        )

    def _evaluate_structure(
        self,
        data,
        confirmed_at=None
    ):
        structure_score = 0
        reasons = []

        market_trend = self.market_structure.trend(data)
        bos = self.market_structure.detect_bos(data)
        choch = self.market_structure.detect_choch(data)

        if market_trend == "BULLISH":
            structure_score += 10
            reasons.append("Market structure bullish")

        elif market_trend == "BEARISH":
            structure_score -= 10
            reasons.append("Market structure bearish")

        if bos == "BULLISH BOS":
            structure_score += 10
            reasons.append("Bullish break of structure")

        elif bos == "BEARISH BOS":
            structure_score -= 10
            reasons.append("Bearish break of structure")

        if choch == "BEARISH CHoCH":
            structure_score -= 15
            reasons.append("Bearish change of character")

        elif choch == "BULLISH CHoCH":
            structure_score += 15
            reasons.append("Bullish change of character")

        return MarketStructureResult(
            score=structure_score,
            reasons=tuple(reasons),
            trend=(
                market_trend
                if market_trend in {
                    "BULLISH",
                    "BEARISH"
                }
                else "NEUTRAL"
            ),
            confirmed_at=confirmed_at,
            bos=bos,
            choch=choch
        )

    def _confirm_momentum(self, latest):
        bullish_momentum = (
            latest["MACD"] > latest["MACD_SIGNAL"]
            and 55 <= latest["RSI"] <= 70
            and latest["STOCH_RSI"] > 20
            and latest["STOCH_RSI"] < 80
        )

        bearish_momentum = (
            latest["MACD"] < latest["MACD_SIGNAL"]
            and 30 <= latest["RSI"] <= 45
            and latest["STOCH_RSI"] > 20
            and latest["STOCH_RSI"] < 80
        )

        if bullish_momentum:
            return MomentumResult(
                score=20,
                reasons=("Bullish momentum confirmed",)
            )

        if bearish_momentum:
            return MomentumResult(
                score=-20,
                reasons=("Bearish momentum confirmed",)
            )

        return MomentumResult(
            score=0,
            reasons=("Weak momentum",)
        )

    def _confirm_volume(
        self,
        data,
        symbol,
        latest,
        directional_score,
        strict_direction=False
    ):
        volume_score = 0
        quality_score = 0
        reasons = []

        if not symbol.endswith("=X"):
            participation = (
                len(data) > 1
                and latest["volume"] > latest["VOL_SMA20"]
            )
            obv_change = (
                latest["OBV"] - data.iloc[-2]["OBV"]
                if len(data) > 1
                else 0
            )
            legacy_volume_ok = (
                participation
                and obv_change > 0
            )

            if legacy_volume_ok:
                if directional_score > 0:
                    volume_score = 15
                    reasons.append("Volume confirms BUY")

                elif directional_score < 0:
                    volume_score = -15
                    if not strict_direction:
                        reasons.append("Volume confirms SELL")

            if strict_direction:
                if directional_score > 0 and participation and obv_change > 0:
                    quality_score = 15

                elif (
                    directional_score < 0
                    and participation
                    and obv_change < 0
                ):
                    quality_score = -15
                    reasons.append("Volume confirms SELL")

                else:
                    reasons.append("Weak volume")

            elif not legacy_volume_ok:
                reasons.append("Weak volume")

        else:
            reasons.append("Volume skipped (Forex)")

        return VolumeResult(
            score=volume_score,
            reasons=tuple(reasons),
            quality_score=(
                quality_score
                if strict_direction
                else volume_score
            )
        )

    def _evaluate_quality(
        self,
        setup,
        momentum,
        structure,
        trigger,
        volume,
        latest,
        regime,
        direction=None,
        strict_direction=False
    ):
        result = self.trade_quality.evaluate(
            trend_score=setup.trend_score,
            momentum_score=momentum.score,
            structure_score=structure.score,
            candle_score=trigger.candle_score,
            volume_score=volume.ranking_score,
            adx=latest["ADX"],
            mtf_confirmed=regime.mtf_confirmed,
            direction=(
                direction if strict_direction else None
            ),
            mtf_direction=(
                regime.confirmation
                if (
                    strict_direction
                    and regime.higher_timeframe_available
                    and regime.confirmation
                    in {"BUY", "SELL"}
                )
                else None
            )
        )

        return TradeQualityResult(
            quality=result["quality"],
            approved=result["approved"],
            reasons=tuple(result["reasons"]),
            supporting_factors=tuple(
                result.get("supporting_factors", ())
            ),
            rejected_factors=tuple(
                result.get("rejected_factors", ())
            )
        )

    @staticmethod
    def _eligibility_failures(
        direction,
        trigger,
        momentum,
        structure,
        regime,
        contextual_gate
    ):
        failures = []

        if direction is None:
            failures.append("No directional setup")
            return tuple(failures)

        if not structure.allows(direction):
            failures.append(
                "Market structure conflicts with setup"
            )

        if not momentum.confirms(direction):
            failures.append(
                "Momentum does not confirm setup"
            )

        if not trigger.confirms(direction):
            failures.append(
                "Price action does not confirm setup"
            )

        if not regime.allows(direction):
            failures.append(
                "Higher timeframe conflicts with setup"
            )

        if (
            contextual_gate.enabled
            and (
                not contextual_gate.approved
                or contextual_gate.direction != direction
            )
        ):
            failures.append(
                "Contextual trigger rejected setup"
            )

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
        strict_direction=False
    ):
        score = (
            setup.trend_score
            + momentum.score
            + trigger.candle_score
            + volume.score
            + structure.score
        )

        bullish_checks = [
            setup.trend_score > 0,
            momentum.score > 0,
            structure.score > 0,
            trigger.candle_score > 0
        ]

        bearish_checks = [
            setup.trend_score < 0,
            momentum.score < 0,
            structure.score < 0,
            trigger.candle_score < 0
        ]

        bullish_confirmations = sum(bullish_checks)
        bearish_confirmations = sum(bearish_checks)

        confidence = (
            abs(score)
            + (bullish_confirmations * 5)
            + (bearish_confirmations * 5)
        )

        direction = setup.direction
        eligibility_failures = self._eligibility_failures(
            direction=direction,
            trigger=trigger,
            momentum=momentum,
            structure=structure,
            regime=regime,
            contextual_gate=contextual_gate
        )

        if (
            score >= self.BUY_THRESHOLD
            and bullish_confirmations >= self.MIN_CONFIRMATIONS
            and setup.trend_score > 0
            and structure.score > 0
        ):
            signal = "BUY"

        elif (
            score <= self.SELL_THRESHOLD
            and bearish_confirmations >= self.MIN_CONFIRMATIONS
            and setup.trend_score < 0
            and structure.score < 0
        ):
            signal = "SELL"

        else:
            signal = "HOLD"

        threshold_signal = signal

        if not quality.approved:
            signal = "HOLD"

        reported_failures = (
            eligibility_failures
            if (
                strict_direction
                or threshold_signal in {"BUY", "SELL"}
            )
            else ()
        )

        reasons = (
            setup.reasons
            + momentum.reasons
            + trigger.reasons
            + volume.reasons
            + structure.reasons
            + regime.reasons
            + (f"Trade Quality: {quality.quality}/100",)
            + contextual_gate.reasons
            + tuple(
                "Rejected: " + failure
                for failure in reported_failures
            )
        )

        if signal in {"BUY", "SELL"} and eligibility_failures:
            signal = "HOLD"

        positive_reasons = tuple(
            reason for reason in reasons
            if "Bullish" in reason
            or "confirmed" in reason
            or "bullish" in reason
        )

        negative_reasons = tuple(
            reason for reason in reasons
            if "Bearish" in reason
            or "Weak" in reason
            or "bearish" in reason
            or "Rejected:" in reason
        )

        return SignalDecision(
            signal=signal,
            confidence=(
                quality.quality
                if strict_direction
                else min(confidence, 100)
            ),
            score=score,
            reasons=reasons,
            decision_summary=DecisionSummary(
                positive=positive_reasons,
                warnings=negative_reasons
            )
        )

    def run(self, data, symbol, higher_tf=None):
        trace = []
        self.last_context = None
        self.last_contextual_trigger = None
        input_validation = validate_input_frame(data)

        self._record(trace, "data_validation")

        if not input_validation.valid:
            self._record(trace, "final_decision")
            return SignalDecision(
                signal="HOLD",
                confidence=0,
                score=0,
                reasons=input_validation.reasons
            )

        causal_data = prepare_causal_market_data(
            data,
            higher_tf
        )
        data = causal_data.lower
        higher_tf = causal_data.higher

        latest = validate_data(data)

        self._record(trace, "market_regime")
        market_validation = validate_market_regime(latest)

        if not market_validation.valid:
            self._record(trace, "final_decision")
            return SignalDecision(
                signal="HOLD",
                confidence=0,
                score=0,
                reasons=market_validation.reasons
            )

        feature_validation = validate_strategy_features(
            data
        )

        if not feature_validation.valid:
            self._record(trace, "final_decision")
            return SignalDecision(
                signal="HOLD",
                confidence=0,
                score=0,
                reasons=feature_validation.reasons
            )

        regime = self._evaluate_regime(
            higher_tf,
            data,
            confirmed_at=(
                causal_data.htf_confirmed_at
                if causal_data.enabled
                else None
            )
        )

        self._record(trace, "market_structure")
        structure = self._evaluate_structure(
            data,
            confirmed_at=(
                causal_data.decision_time
                if causal_data.enabled
                else None
            )
        )

        self._record(trace, "setup_detection")
        setup = self.setup_detector.detect(latest)

        contextual_setup = None

        if causal_data.enabled:
            contextual_setup = (
                self.setup_detector.create_contextual_setup(
                    setup=setup,
                    decision_time=causal_data.decision_time,
                    bar_duration=causal_data.bar_duration,
                    htf_regime=regime.regime,
                    structure_trend=structure.trend,
                    symbol=symbol
                )
            )

        self._record(trace, "context_builder")
        context = None

        if causal_data.enabled:
            context = self.contextual_adapter.build_context(
                data=data,
                decision_time=causal_data.decision_time,
                regime=regime,
                structure=structure,
                market_structure=self.market_structure
            )

        self.last_context = context

        self._record(trace, "contextual_trigger")
        trigger = self.trigger_detector.detect(data)
        contextual_gate = ContextualGateResult.bypassed()

        if causal_data.enabled:
            contextual_gate = (
                self.contextual_adapter.evaluate_trigger(
                    context,
                    contextual_setup
                )
            )

        self.last_contextual_trigger = (
            contextual_gate.output
        )

        self._record(trace, "momentum_confirmation")
        momentum = self._confirm_momentum(latest)
        volume = self._confirm_volume(
            data=data,
            symbol=symbol,
            latest=latest,
            directional_score=(
                setup.trend_score
                + momentum.score
                + trigger.candle_score
            ),
            strict_direction=causal_data.enabled
        )

        self._record(trace, "trade_quality")
        quality = self._evaluate_quality(
            setup=setup,
            momentum=momentum,
            structure=structure,
            trigger=trigger,
            volume=volume,
            latest=latest,
            regime=regime,
            direction=setup.direction,
            strict_direction=causal_data.enabled
        )

        self._record(trace, "risk_validation")
        risk_validation = validate_risk()

        self._record(trace, "final_decision")
        decision = self._final_decision(
            setup=setup,
            trigger=trigger,
            momentum=momentum,
            volume=volume,
            structure=structure,
            regime=regime,
            quality=quality,
            contextual_gate=contextual_gate,
            strict_direction=causal_data.enabled
        )

        if not risk_validation.valid:
            return SignalDecision(
                signal="HOLD",
                confidence=decision.confidence,
                score=decision.score,
                reasons=decision.reasons,
                decision_summary=decision.decision_summary
            )

        return decision
