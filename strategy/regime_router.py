"""Causal strategy routing across trend, range, and breakout regimes.

The router keeps timeframe roles separate and fails closed when the current
market state does not satisfy a strategy family.  ``confidence`` always means
trade-decision confidence; regime classification confidence is exposed
separately as ``regime_confidence`` so a high-confidence RANGE/BREAKOUT regime
can no longer look like a high-confidence trade while the actual decision is
HOLD.
"""

from __future__ import annotations

import logging
from math import isfinite
from typing import Any

from ai.decision_analyzer import AIDecisionAnalyzer
from data.timeframes import frame_decision_time
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from strategy.regime_detector import (
    REGIME_BREAKOUT,
    REGIME_HIGH_VOLATILITY,
    REGIME_LOW_VOLATILITY,
    REGIME_RANGE,
    REGIME_TREND_DOWN,
    REGIME_TREND_UP,
    REGIME_UNKNOWN,
    MarketRegimeDetector,
)

logger = logging.getLogger(__name__)


class RegimeStrategyRouter:
    """Select one strategy family without allowing regimes to mix roles."""

    def __init__(
        self,
        trend_engine: Any,
        *,
        higher_timeframe: str,
        lower_timeframe: str,
        detector: MarketRegimeDetector | None = None,
        mtf_analyzer: MultiTimeframeAnalyzer | None = None,
        decision_analyzer: AIDecisionAnalyzer | None = None,
        minimum_regime_confidence: float = 45.0,
    ) -> None:
        self.trend_engine = trend_engine
        self.detector = detector or MarketRegimeDetector()
        self.mtf = mtf_analyzer or MultiTimeframeAnalyzer.production(
            higher_timeframe=higher_timeframe,
            lower_timeframe=lower_timeframe,
        )
        self.decision_analyzer = decision_analyzer or AIDecisionAnalyzer()
        self.higher_timeframe = higher_timeframe
        self.lower_timeframe = lower_timeframe
        self.minimum_regime_confidence = float(minimum_regime_confidence)

    def generate_signal(self, data, symbol, higher_tf=None) -> dict[str, Any]:
        return self.generate_analysis(data, symbol, higher_tf)

    def generate_analysis(self, data, symbol, higher_tf=None) -> dict[str, Any]:
        """Return one routed, explainable decision and log every HOLD reason."""
        result = self._generate_analysis(data, symbol, higher_tf)
        if result.get("signal") == "HOLD":
            reasons = "; ".join(str(item) for item in result.get("reasons", ()) if item)
            logger.info(
                "ROUTED HOLD detail %s | strategy=%s | regime=%s | "
                "regime_confidence=%s | trade_confidence=%s | htf=%s | reasons=%s",
                symbol,
                result.get("strategy", "UNKNOWN"),
                result.get("regime", "UNKNOWN"),
                result.get("regime_confidence", 0),
                result.get("confidence", 0),
                result.get("higher_timeframe_regime", "UNKNOWN"),
                reasons or "none",
            )
        return result

    def _generate_analysis(self, data, symbol, higher_tf=None) -> dict[str, Any]:
        try:
            regime = self.detector.detect(data)
        except (TypeError, ValueError) as exc:
            return self._hold(
                regime=REGIME_UNKNOWN,
                regime_confidence=0.0,
                reasons=[f"Regime detection failed closed: {exc}"],
            )

        regime_name = str(regime.get("regime", REGIME_UNKNOWN))
        regime_confidence = self._finite_number(regime.get("confidence"), 0.0)
        risk_multiplier = self._bounded_multiplier(regime.get("risk_multiplier", 0.0))

        if regime_confidence < self.minimum_regime_confidence:
            return self._hold(
                regime=regime_name,
                regime_confidence=regime_confidence,
                reasons=[
                    f"Regime confidence below {self.minimum_regime_confidence:.0f}%",
                    *regime.get("reasons", []),
                ],
            )

        htf_regime = self._higher_timeframe_regime(data, higher_tf)

        if regime_name in {REGIME_TREND_UP, REGIME_TREND_DOWN}:
            decision = self.trend_engine.generate_analysis(data, symbol, higher_tf)
            expected = "BUY" if regime_name == REGIME_TREND_UP else "SELL"
            if decision.get("signal") not in {expected, "HOLD"}:
                return self._hold(
                    regime=regime_name,
                    regime_confidence=regime_confidence,
                    strategy="TREND",
                    reasons=["Trend strategy direction conflicts with detected regime"],
                )
            return self._decorate(
                decision,
                regime=regime_name,
                regime_confidence=regime_confidence,
                strategy="TREND",
                risk_multiplier=risk_multiplier,
                htf_regime=htf_regime,
            )

        if regime_name == REGIME_RANGE:
            decision = self._range_reversion(data, regime)
            signal = decision.get("signal", "HOLD")
            if signal in {"BUY", "SELL"} and higher_tf is not None:
                expected_htf = "BULLISH" if signal == "BUY" else "BEARISH"
                if htf_regime not in {expected_htf, "NEUTRAL"}:
                    return self._hold(
                        regime=regime_name,
                        regime_confidence=regime_confidence,
                        strategy="RANGE_REVERSION",
                        reasons=[
                            f"Range {signal} conflicts with {htf_regime} higher timeframe"
                        ],
                        htf_regime=htf_regime,
                    )
            return self._decorate(
                decision,
                regime=regime_name,
                regime_confidence=regime_confidence,
                strategy="RANGE_REVERSION",
                risk_multiplier=risk_multiplier if signal in {"BUY", "SELL"} else 0.0,
                htf_regime=htf_regime,
            )

        if regime_name == REGIME_BREAKOUT:
            decision = self._breakout(data, regime, htf_regime, higher_tf)
            return self._decorate(
                decision,
                regime=regime_name,
                regime_confidence=regime_confidence,
                strategy="BREAKOUT",
                risk_multiplier=risk_multiplier if decision.get("signal") in {"BUY", "SELL"} else 0.0,
                htf_regime=htf_regime,
            )

        reason = {
            REGIME_LOW_VOLATILITY: "Low-volatility regime blocks new entries",
            REGIME_HIGH_VOLATILITY: "Unstructured high-volatility regime blocks new entries",
            REGIME_UNKNOWN: "Unknown market regime blocks new entries",
        }.get(regime_name, "Unsupported market regime blocks new entries")
        return self._hold(
            regime=regime_name,
            regime_confidence=regime_confidence,
            reasons=[reason, *regime.get("reasons", [])],
        )

    def _higher_timeframe_regime(self, data, higher_tf) -> str:
        if higher_tf is None:
            return "NEUTRAL"
        try:
            decision_time = frame_decision_time(data, self.lower_timeframe)
            return self.mtf.get_regime(
                higher_tf,
                decision_time=decision_time,
                timeframe=self.higher_timeframe,
            )
        except (KeyError, TypeError, ValueError):
            return "UNKNOWN"

    def _range_reversion(self, data, regime) -> dict[str, Any]:
        required = {"open", "close", "RSI", "BB_UPPER", "BB_LOWER", "ATR"}
        missing = required.difference(data.columns)
        if missing or len(data) < 2:
            return self._base_decision(
                "HOLD", 0, 0,
                ["Insufficient completed-candle features for range strategy"],
            )

        previous = data.iloc[-2]
        latest = data.iloc[-1]
        values = [latest[column] for column in required] + [
            previous["close"], previous["RSI"],
            previous["BB_UPPER"], previous["BB_LOWER"],
        ]
        if not all(self._is_finite(value) for value in values):
            return self._base_decision("HOLD", 0, 0, ["Range strategy features are non-finite"])

        close = float(latest["close"])
        open_price = float(latest["open"])
        rsi = float(latest["RSI"])
        previous_rsi = float(previous["RSI"])
        lower = float(latest["BB_LOWER"])
        upper = float(latest["BB_UPPER"])
        previous_close = float(previous["close"])
        previous_lower = float(previous["BB_LOWER"])
        previous_upper = float(previous["BB_UPPER"])

        bullish_reentry = (
            previous_close < previous_lower
            and close >= lower
            and close > open_price
            and rsi <= 40.0
            and rsi > previous_rsi
        )
        bearish_reentry = (
            previous_close > previous_upper
            and close <= upper
            and close < open_price
            and rsi >= 60.0
            and rsi < previous_rsi
        )
        trade_confidence = int(min(85.0, self._finite_number(regime.get("confidence"), 0.0)))

        if bullish_reentry:
            return self._base_decision(
                "BUY", trade_confidence, trade_confidence,
                [
                    "Price re-entered the lower Bollinger Band",
                    "RSI recovered from range exhaustion",
                    "Bullish completed candle confirms reversion",
                ],
            )
        if bearish_reentry:
            return self._base_decision(
                "SELL", trade_confidence, -trade_confidence,
                [
                    "Price re-entered the upper Bollinger Band",
                    "RSI fell from range exhaustion",
                    "Bearish completed candle confirms reversion",
                ],
            )
        return self._base_decision(
            "HOLD", 0, 0,
            ["Range detected but no confirmed Bollinger/RSI re-entry"],
        )

    def _breakout(self, data, regime, htf_regime, higher_tf) -> dict[str, Any]:
        if len(data) < 21:
            return self._base_decision("HOLD", 0, 0, ["Insufficient history for breakout confirmation"])
        latest = data.iloc[-1]
        required = ("open", "high", "low", "close", "ATR", "ADX")
        if any(column not in data.columns for column in required):
            return self._base_decision("HOLD", 0, 0, ["Breakout confirmation features are missing"])
        if not all(self._is_finite(latest[column]) for column in required):
            return self._base_decision("HOLD", 0, 0, ["Breakout features are non-finite"])

        direction = str(regime.get("direction", "NEUTRAL"))
        signal = "BUY" if direction == "BULLISH" else "SELL" if direction == "BEARISH" else "HOLD"
        expected_htf = "BULLISH" if signal == "BUY" else "BEARISH"
        if higher_tf is not None and htf_regime not in {expected_htf, "NEUTRAL"}:
            return self._base_decision("HOLD", 0, 0, ["Breakout direction conflicts with higher timeframe"])

        atr = float(latest["ATR"])
        body = abs(float(latest["close"]) - float(latest["open"]))
        adx = float(latest["ADX"])
        prior = data.iloc[-21:-1]
        prior_high = float(prior["high"].max())
        prior_low = float(prior["low"].min())
        confirmed = (
            signal == "BUY" and float(latest["close"]) > prior_high
        ) or (
            signal == "SELL" and float(latest["close"]) < prior_low
        )
        if signal == "HOLD" or not confirmed or atr <= 0 or body < 0.5 * atr or adx < 25:
            return self._base_decision(
                "HOLD", 0, 0,
                ["Breakout regime lacks a strong close/ATR/ADX confirmation"],
            )

        trade_confidence = int(min(90.0, self._finite_number(regime.get("confidence"), 0.0)))
        return self._base_decision(
            signal,
            trade_confidence,
            trade_confidence if signal == "BUY" else -trade_confidence,
            [
                f"{signal} close confirmed beyond the prior 20-candle range",
                "Breakout candle body is at least 0.5 ATR",
                "ADX confirms directional expansion",
            ],
        )

    def _decorate(
        self,
        decision,
        *,
        regime,
        regime_confidence,
        strategy,
        risk_multiplier,
        htf_regime,
    ) -> dict[str, Any]:
        result = dict(decision)
        result["regime"] = regime
        result["regime_confidence"] = round(float(regime_confidence), 1)
        result["strategy"] = strategy
        result["risk_multiplier"] = self._bounded_multiplier(risk_multiplier)
        result["higher_timeframe_regime"] = htf_regime
        if "decision_report" not in result:
            report = self.decision_analyzer.analyze(
                signal=result.get("signal", "HOLD"),
                confidence=result.get("confidence", 0),
                score=result.get("score", 0),
                reasons=result.get("reasons", []),
                decision_summary=result.get("decision_summary", {}),
            )
            report["report_text"] = self.decision_analyzer.format_report(report)
            result["decision_report"] = report
        return result

    def _hold(
        self,
        *,
        regime,
        regime_confidence,
        reasons,
        strategy="NO_TRADE",
        htf_regime="UNKNOWN",
    ) -> dict[str, Any]:
        return self._decorate(
            self._base_decision("HOLD", 0, 0, reasons),
            regime=regime,
            regime_confidence=regime_confidence,
            strategy=strategy,
            risk_multiplier=0.0,
            htf_regime=htf_regime,
        )

    @staticmethod
    def _base_decision(signal, confidence, score, reasons) -> dict[str, Any]:
        positive = [reason for reason in reasons if signal in {"BUY", "SELL"}]
        warnings = [reason for reason in reasons if signal == "HOLD"]
        return {
            "signal": signal,
            "confidence": int(max(0, min(100, confidence))),
            "score": int(score),
            "reasons": list(reasons),
            "decision_summary": {"positive": positive, "warnings": warnings},
        }

    @staticmethod
    def _is_finite(value) -> bool:
        try:
            return isfinite(float(value))
        except (TypeError, ValueError):
            return False

    @classmethod
    def _finite_number(cls, value, fallback) -> float:
        return float(value) if cls._is_finite(value) else float(fallback)

    @classmethod
    def _bounded_multiplier(cls, value) -> float:
        return max(0.0, min(1.0, cls._finite_number(value, 0.0)))


__all__ = ["RegimeStrategyRouter"]