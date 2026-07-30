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
    """
    AAQTS Signal Engine

    Pipeline

    1. Regime Detection
    2. Trend Analysis
    3. Momentum Analysis
    4. Candle Patterns
    5. Volume Validation
    6. Market Structure
    7. Initial Signal
    8. Multi-Timeframe Validation
    9. Trade Quality
    10. Regime Validation
    11. AI Decision Report
    """

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

        ###########################################################
        # LAYER 1
        # MARKET REGIME
        ###########################################################

        if (
            latest["ADX"] < MIN_ADX
            and regime["regime"] not in {"RANGE", "BREAKOUT"}
        ):
            return {
                "signal": "HOLD",
                "confidence": 0,
                "score": 0,
                "regime": regime,
                "reasons": [
                    reasons[0],
                    f"Weak market (ADX below {MIN_ADX:g})",
                ],
            }

        ###########################################################
        # LAYER 2
        # TREND
        ###########################################################

        trend_score = 0

        bullish_trend = (
            latest["EMA_20"] > latest["EMA_50"]
            and latest["EMA_50"] > latest["EMA_200"]
            and latest["SUPERTREND"]
        )

        bearish_trend = (
            latest["EMA_20"] < latest["EMA_50"]
            and latest["EMA_50"] < latest["EMA_200"]
            and not latest["SUPERTREND"]
        )

        if bullish_trend:

            trend_score = 30
            reasons.append("Bullish EMA alignment")

        elif bearish_trend:

            trend_score = -30
            reasons.append("Bearish EMA alignment")

        else:

            reasons.append("Trend not aligned")

        score += trend_score

        ###########################################################
        # LAYER 3
        # MOMENTUM
        ###########################################################

        momentum_score = 0

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

            momentum_score = 20
            reasons.append("Bullish momentum confirmed")

        elif bearish_momentum:

            momentum_score = -20
            reasons.append("Bearish momentum confirmed")

        else:

            reasons.append("Weak momentum")

        score += momentum_score

        ###########################################################
        # LAYER 4
        # PRICE ACTION
        ###########################################################

        candle_score = 0

        patterns = self.candles.analyze(data)

        for pattern in patterns:

            if pattern in ("Bullish engulfing", "BULLISH PIN BAR"):

                candle_score += 10
                reasons.append(f"Bullish price action: {pattern}")

            elif pattern in ("Bearish engulfing", "BEARISH PIN BAR"):

                candle_score -= 10
                reasons.append(f"Bearish price action: {pattern}")

            elif pattern == "STRONG BULLISH CANDLE":

                candle_score += 5
                reasons.append("Bullish momentum candle")

            elif pattern == "STRONG BEARISH CANDLE":

                candle_score -= 5
                reasons.append("Bearish momentum candle")

            else:

                reasons.append(pattern)

        score += candle_score

        ###########################################################
        # LAYER 5
        # VOLUME
        ###########################################################

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

        ###########################################################
        # LAYER 6
        # MARKET STRUCTURE
        ###########################################################

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

        if choch == "BULLISH CHoCH":

            structure_score += 15
            reasons.append("Bullish change of character")

        elif choch == "BEARISH CHoCH":

            structure_score -= 15
            reasons.append("Bearish change of character")

        score += structure_score

                ###########################################################
        # LAYER 7
        # INITIAL SIGNAL DECISION
        ###########################################################

        bullish_confirmations = sum([
            trend_score > 0,
            momentum_score > 0,
            candle_score > 0,
            structure_score > 0,
        ])

        bearish_confirmations = sum([
            trend_score < 0,
            momentum_score < 0,
            candle_score < 0,
            structure_score < 0,
        ])

        if (
            score >= SIGNAL_SCORE_THRESHOLD
            and bullish_confirmations >= MIN_SIGNAL_CONFIRMATIONS
        ):
            signal = "BUY"

        elif (
            score <= -SIGNAL_SCORE_THRESHOLD
            and bearish_confirmations >= MIN_SIGNAL_CONFIRMATIONS
        ):
            signal = "SELL"

        else:
            signal = "HOLD"

        ###########################################################
        # LAYER 8
        # MULTI TIMEFRAME VALIDATION
        ###########################################################

        mtf_confirmed = higher_tf is None
        mtf_direction = "NONE"

        if higher_tf is not None:

            mtf_result = self.mtf.analyze(higher_tf, data)
            mtf_direction = mtf_result.get("confirmation", "HOLD")

            if signal in ("BUY", "SELL"):

                if mtf_direction == signal:

                    mtf_confirmed = True
                    reasons.append(
                        f"Higher timeframe confirms {signal}"
                    )

                else:

                    mtf_confirmed = False

                    reasons.append(
                        f"Higher timeframe rejected {signal} "
                        f"(Higher TF = {mtf_direction})"
                    )

                    signal = "HOLD"

                    reasons.append(
                        "Trade blocked due to higher timeframe conflict"
                    )

            else:

                mtf_confirmed = False
                reasons.append(
                    "No executable signal for multi-timeframe confirmation"
                )

        ###########################################################
        # LAYER 9
        # CONFIDENCE ENGINE
        ###########################################################

        confidence = (
            abs(trend_score)
            + abs(momentum_score)
            + abs(candle_score)
            + abs(structure_score)
            + abs(volume_score)
        )

        confidence *= regime.get("confidence", 100) / 100

        if mtf_confirmed:
            confidence += 10

        confidence = round(min(confidence, 100), 2)

        ###########################################################
        # LAYER 10
        # TRADE QUALITY
        ###########################################################

        quality = self.trade_quality.evaluate(
            trend_score=trend_score,
            momentum_score=momentum_score,
            structure_score=structure_score,
            candle_score=candle_score,
            volume_score=volume_score,
            adx=latest["ADX"],
            mtf_confirmed=mtf_confirmed,
        )

        reasons.append(
            f"Trade Quality: {quality['quality']}/100"
        )

        if not quality["approved"]:

            signal = "HOLD"

            reasons.append(
                "Trade rejected by Trade Quality filter"
            )

        ###########################################################
        # LAYER 11
        # REGIME VALIDATION
        ###########################################################

        allowed, regime_reason = (
            self.regime_detector.allows_signal(
                regime,
                signal,
            )
        )

        reasons.append(regime_reason)

        if not allowed:

            signal = "HOLD"

            reasons.append(
                "Trade rejected by Market Regime"
            )

                    ###########################################################
        # LAYER 12
        # DECISION SUMMARY
        ###########################################################

        positive_reasons = []
        warning_reasons = []
        rejection_reasons = []

        for reason in reasons:

            text = reason.lower()

            if any(keyword in text for keyword in [
                "bullish",
                "confirmed",
                "break of structure",
                "higher timeframe confirms",
                "quality",
                "compatible",
            ]):
                positive_reasons.append(reason)

            elif any(keyword in text for keyword in [
                "bearish",
                "weak",
                "rejected",
                "conflict",
                "blocked",
                "not aligned",
            ]):
                warning_reasons.append(reason)

            if any(keyword in text for keyword in [
                "rejected",
                "blocked",
                "conflict",
            ]):
                rejection_reasons.append(reason)

        ###########################################################
        # LAYER 13
        # AI DECISION ANALYZER
        ###########################################################

        decision_report = self.decision_analyzer.analyze(

            signal=signal,

            confidence=confidence,

            score=score,

            reasons=reasons,

            trend_score=trend_score,

            momentum_score=momentum_score,

            structure_score=structure_score,

            candle_score=candle_score,

            volume_score=volume_score,

            trade_quality=quality["quality"],

            regime=regime,

            mtf_confirmed=mtf_confirmed,

            market_trend=market_trend,

            bos=bos,

            choch=choch,

            adx=latest["ADX"],

            rsi=latest["RSI"],

            macd=latest["MACD"],

            macd_signal=latest["MACD_SIGNAL"],

            decision_summary={

                "positive": positive_reasons,

                "warnings": warning_reasons,

                "rejections": rejection_reasons,

            }

        )

        ###########################################################
        # REPORT GENERATION
        ###########################################################

        decision_report["report_text"] = (
            self.decision_analyzer.format_report(
                decision_report
            )
        )
