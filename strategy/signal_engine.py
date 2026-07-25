from structure.market_structure import MarketStructure






class SignalEngine:

    def __init__(self):
        self.market_structure = MarketStructure()


    def generate_signal(self, data, symbol):

        latest = data.iloc[-1]

        score = 0
        reasons = []

        # ==========================
        # LAYER 1 - MARKET REGIME
        # ==========================
        if latest["ADX"] < 25:
            return {
                "signal": "HOLD",
                "confidence": 0,
                "score": 0,
                "reasons": [
                    "Weak market (ADX below 25)"
                ]
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

        momentum = 0

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

            momentum = 20
            reasons.append("Bullish momentum confirmed")

        elif bearish_momentum:

            momentum = -20
            reasons.append("Bearish momentum confirmed")

        else:

            reasons.append("Weak momentum")
        score += momentum
                # ==========================


        # LAYER 4 - VOLUME
        # ==========================

        volume_score = 0

        # Forex has no reliable centralized volume on Yahoo Finance
        if not symbol.endswith("=X"):

            volume_ok = (
                latest["Volume"] > latest["VOL_SMA20"]
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
        # LAYER 5 - MARKET STRUCTURE
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
        # CONFIDENCE
        # ==========================
        confidence = abs(score)

        if score >= 65:
            signal = "BUY"

        elif score <= -50:
            signal = "SELL"

        else:
            signal = "HOLD"

        return {

            "signal": signal,

            "confidence": min(confidence, 100),

            "score": score,

            "reasons": reasons

        }