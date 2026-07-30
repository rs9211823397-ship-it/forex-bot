from structure.market_structure import MarketStructure
from price_action.candles import CandlePatterns
from strategy.multi_timeframe import MultiTimeframeAnalyzer
from strategy.regime_detector import MarketRegimeDetector
from ai.decision_analyzer import AIDecisionAnalyzer
from ai.trade_quality import TradeQuality
from config.settings import (
    MIN_ADX,
    MIN_SIGNAL_CONFIRMATIONS,
    SIGNAL_SCORE_THRESHOLD,
)


class SignalEngine:

    def __init__(self):
        self.market_structure = MarketStructure()
        self.candles = CandlePatterns()
        self.mtf = MultiTimeframeAnalyzer()
        self.trade_quality = TradeQuality()
        self.regime_detector = MarketRegimeDetector()
        self.decision_analyzer = AIDecisionAnalyzer()

    def generate_signal(self, data, symbol, higher_tf=None):

        latest = data.iloc[-1]
        regime = self.regime_detector.detect(data)

        score = 0
        reasons = [
            f"Market regime: {regime['regime']} ({regime['confidence']:.1f}%)"
        ]

        # ==========================
        # LAYER 1 - MARKET REGIME
        # ==========================
        if latest["ADX"] < MIN_ADX and regime["regime"] not in {"RANGE", "BREAKOUT"}:
            return {
                "signal": "HOLD",
                "confidence": 0,
                "score": 0,
                "regime": regime,
                "reasons": [
                    f"Market regime: {regime['regime']} ({regime['confidence']:.1f}%)",
                    f"Weak market (ADX below {MIN_ADX:g})",
                ],
            }

        # ==========================
        # LAYER 2 - TREND
        # ==========================
        trend_score = 0

        if (
            latest["EMA_20"] > latest["EMA_50"]
            and latest["EMA_50"] > latest["EMA_200"]
            and latest["SUPERTREND"]
        ):
            trend_score = 30
            reasons.append("Bullish EMA alignment")

        elif (
            latest["EMA_20"] < latest["EMA_50"]
            and latest["EMA_50"] < latest["EMA_200"]
            and not latest["SUPERTREND"]
        ):
            trend_score = -30
            reasons.append("Bearish EMA alignment")

        else:
            reasons.append("Trend not aligned")

        score += trend_score

        # ==========================
        # LAYER 3 - MOMENTUM
        # ==========================
        momentum = 0

        bullish_momentum = (
            latest["MACD"] > latest["MACD_SIGNAL"]
            and 50 <= latest["RSI"] <= 72
            and 15 < latest["STOCH_RSI"] < 85
        )

        bearish_momentum = (
            latest["MACD"] < latest["MACD_SIGNAL"]
            and 28 <= latest["RSI"] <= 50
            and 15 < latest["STOCH_RSI"] < 85
        )

        if bullish_momentum:
            momentum = 20
            reasons.append("Bullish momentum confirmed")

        elif bearish_momentum:
            momentum = -20
            reasons.append("Bearish momentum confirmed")

        else:
            reasons.append("Weak momentum")

        score += momentum

        # ==========================
        # LAYER 4 - PRICE ACTION
        # ==========================
        candle_score = 0
        patterns = self.candles.analyze(data)

        for pattern in patterns:
            if pattern in ["Bullish engulfing", "BULLISH PIN BAR"]:
                candle_score += 10
                reasons.append("Bullish price action: " + pattern)
            elif pattern in ["Bearish engulfing", "BEARISH PIN BAR"]:
                candle_score -= 10
                reasons.append("Bearish price action: " + pattern)
            elif pattern == "STRONG BULLISH CANDLE":
                candle_score += 5
                reasons.append("Bullish momentum candle")
            elif pattern == "STRONG BEARISH CANDLE":
                candle_score -= 5
                reasons.append("Bearish momentum candle")
            else:
                reasons.append(pattern)

        score += candle_score

        # ==========================
        # LAYER 5 - VOLUME
        # ==========================
        volume_score = 0

        if not symbol.endswith("=X"):
            volume_ok = (
                len(data) > 1
                and latest["volume"] > latest["VOL_SMA20"]
                and latest["OBV"] > data.iloc[-2]["OBV"]
            )
            if volume_ok:
                if score > 0:
                    volume_score = 15
                    reasons.append("Volume confirms BUY")
                elif score < 0:
                    volume_score = -15
                    reasons.append("Volume confirms SELL")
            else:
                reasons.append("Weak volume")
        else:
            reasons.append("Volume skipped (Forex)")

        score += volume_score

        # ==========================
        # LAYER 6 - MARKET STRUCTURE
        # ==========================
        structure_score = 0
        market_trend = self.market_structure.trend(data)
        bos = self.market_structure.detect_bos(data)
        choch = self.market_structure.detect_choch(data)

        if market_trend == "BULLISH":
            structure_score += 20
            reasons.append("Market structure bullish")
        elif market_trend == "BEARISH":
            structure_score -= 20
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

        score += structure_score

        # ==========================
        # LAYER 7 - MULTI TIMEFRAME
        # ==========================
        mtf_confirmed = True
        if higher_tf is not None:
            mtf_result = self.mtf.analyze(higher_tf, data)
            if mtf_result["confirmation"] == "BUY":
                mtf_confirmed = True
                reasons.append("Multi timeframe BUY confirmation")
            elif mtf_result["confirmation"] == "SELL":
                mtf_confirmed = True
                reasons.append("Multi timeframe SELL confirmation")
            else:
                mtf_confirmed = False
                reasons.append("Multi timeframe not confirmed")

        confidence = abs(score)
        bullish_checks = [trend_score > 0, momentum > 0, candle_score > 0, structure_score > 0]
        bearish_checks = [trend_score < 0, momentum < 0, candle_score < 0, structure_score < 0]
        bullish_confirmations = sum(bullish_checks)
        bearish_confirmations = sum(bearish_checks)

        if score >= SIGNAL_SCORE_THRESHOLD and bullish_confirmations >= MIN_SIGNAL_CONFIRMATIONS:
            signal = "BUY"
        elif score <= -SIGNAL_SCORE_THRESHOLD and bearish_confirmations >= MIN_SIGNAL_CONFIRMATIONS:
            signal = "SELL"
        else:
            signal = "HOLD"

        quality = self.trade_quality.evaluate(
            trend_score=trend_score,
            momentum_score=momentum,
            structure_score=structure_score,
            candle_score=candle_score,
            volume_score=volume_score,
            adx=latest["ADX"],
            mtf_confirmed=mtf_confirmed,
        )
        reasons.append(f"Trade Quality: {quality['quality']}/100")
        if not quality["approved"]:
            signal = "HOLD"

        allowed, regime_reason = self.regime_detector.allows_signal(regime, signal)
        reasons.append(regime_reason)
        if not allowed:
            signal = "HOLD"

        positive_reasons = [
            r for r in reasons
            if "Bullish" in r or "confirmed" in r or "bullish" in r or "compatible" in r
        ]
        negative_reasons = [
            r for r in reasons
            if "Bearish" in r or "Weak" in r or "bearish" in r or "blocks" in r or "conflicts" in r
        ]

        decision_report = self.decision_analyzer.analyze(
            signal=signal,
            confidence=min(confidence, 100),
            score=score,
            reasons=reasons,
            decision_summary={
                "positive": positive_reasons,
                "warnings": negative_reasons,
            },
        )
        decision_report["report_text"] = self.decision_analyzer.format_report(decision_report)

        return {
            "signal": signal,
            "confidence": min(confidence, 100),
            "score": score,
            "regime": regime,
            "reasons": reasons,
            "decision_summary": {
                "positive": positive_reasons,
                "warnings": negative_reasons,
            },
            "decision_report": decision_report,
            "rejection_reasons": decision_report.get("rejection_reasons", []),
        }
