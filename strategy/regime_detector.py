from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import math
import pandas as pd


###############################################################################
# REGIME CONSTANTS
###############################################################################

REGIME_TREND_UP = "TREND_UP"
REGIME_TREND_DOWN = "TREND_DOWN"
REGIME_RANGE = "RANGE"
REGIME_BREAKOUT = "BREAKOUT"
REGIME_HIGH_VOLATILITY = "HIGH_VOLATILITY"
REGIME_LOW_VOLATILITY = "LOW_VOLATILITY"
REGIME_UNKNOWN = "UNKNOWN"


###############################################################################
# RESULT OBJECT
###############################################################################

@dataclass(frozen=True)
class RegimeResult:

    regime: str

    confidence: float

    trend_score: float

    range_score: float

    breakout_score: float

    volatility_score: float

    direction: str

    market_bias: str

    risk_multiplier: float

    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:

        result = asdict(self)

        result["reasons"] = list(self.reasons)

        return result


###############################################################################
# DETECTOR
###############################################################################

class MarketRegimeDetector:

    REQUIRED_COLUMNS = {

        "close",

        "EMA_20",

        "EMA_50",

        "EMA_200",

        "ADX",

        "ATR",

        "BB_UPPER",

        "BB_LOWER",

        "BB_MIDDLE",

    }

    def __init__(

        self,

        *,

        adx_trend_threshold: float = 25.0,

        adx_range_threshold: float = 20.0,

        lookback: int = 100,

        slope_lookback: int = 5,

        breakout_lookback: int = 20,

    ):

        self.adx_trend_threshold = float(adx_trend_threshold)

        self.adx_range_threshold = float(adx_range_threshold)

        self.lookback = int(lookback)

        self.slope_lookback = int(slope_lookback)

        self.breakout_lookback = int(breakout_lookback)

    ############################################################################
    # VALIDATION
    ############################################################################

    def _validate(self, data: pd.DataFrame):

        if not isinstance(data, pd.DataFrame):

            raise ValueError("Input must be pandas DataFrame")

        if data.empty:

            raise ValueError("Empty dataframe")

        missing = self.REQUIRED_COLUMNS.difference(data.columns)

        if missing:

            raise ValueError(
                f"Missing regime columns: {', '.join(sorted(missing))}"
            )

    ############################################################################
    # HELPERS
    ############################################################################

    def _normalized_slope(

        self,

        series: pd.Series,

        close: float,

    ) -> float:

        values = pd.to_numeric(series, errors="coerce").dropna()

        if len(values) <= self.slope_lookback:

            return 0.0

        return (

            float(values.iloc[-1])

            - float(values.iloc[-1 - self.slope_lookback])

        ) / max(abs(close), 1e-12)

    @staticmethod
    def _bb_width(frame: pd.DataFrame):

        middle = (

            pd.to_numeric(

                frame["BB_MIDDLE"],

                errors="coerce",

            )

            .abs()

            .replace(0, pd.NA)

        )

        return (

            pd.to_numeric(frame["BB_UPPER"], errors="coerce")

            - pd.to_numeric(frame["BB_LOWER"], errors="coerce")

        ) / middle

    @staticmethod
    def _percentile_rank(

        series: pd.Series,

        value: float,

    ) -> float:

        values = pd.to_numeric(

            series,

            errors="coerce",

        ).dropna()

        if values.empty:

            return 50.0

        return float((values <= value).mean() * 100)

            ############################################################################
    # MAIN REGIME DETECTION
    ############################################################################

    def detect(self, data: pd.DataFrame) -> dict[str, Any]:
        """
        Detect the current market regime using only information available
        at the latest completed candle.

        Returns a dictionary containing:

        - regime
        - confidence
        - direction
        - market_bias
        - risk_multiplier
        - trend_score
        - range_score
        - breakout_score
        - volatility_score
        - reasons
        """

        self._validate(data)

        clean = data.replace(
            [math.inf, -math.inf],
            pd.NA,
        ).dropna(
            subset=list(self.REQUIRED_COLUMNS)
        )

        minimum_rows = max(
            self.slope_lookback + 1,
            self.breakout_lookback + 1,
            30,
        )

        if len(clean) < minimum_rows:
            return RegimeResult(
                regime=REGIME_UNKNOWN,
                confidence=0.0,
                trend_score=0.0,
                range_score=0.0,
                breakout_score=0.0,
                volatility_score=0.0,
                direction="NEUTRAL",
                market_bias="NEUTRAL",
                risk_multiplier=0.0,
                reasons=(
                    f"Insufficient regime history "
                    f"({len(clean)}/{minimum_rows})",
                ),
            ).to_dict()

        frame = clean.iloc[-self.lookback:].copy()

        latest = frame.iloc[-1]
        previous = frame.iloc[-2]

        close = float(latest["close"])
        previous_close = float(previous["close"])

        ema20 = float(latest["EMA_20"])
        ema50 = float(latest["EMA_50"])
        ema200 = float(latest["EMA_200"])

        adx = float(latest["ADX"])
        atr = float(latest["ATR"])

        reasons: list[str] = []

        ########################################################################
        # VOLATILITY MEASUREMENTS
        ########################################################################

        atr_percentile = self._percentile_rank(
            frame["ATR"],
            atr,
        )

        bb_width_series = self._bb_width(frame)

        valid_bb_width = pd.to_numeric(
            bb_width_series,
            errors="coerce",
        ).dropna()

        if valid_bb_width.empty:
            current_bb_width = 0.0
            bb_width_percentile = 50.0
        else:
            current_bb_width = float(valid_bb_width.iloc[-1])

            bb_width_percentile = self._percentile_rank(
                valid_bb_width,
                current_bb_width,
            )

        volatility_score = max(
            atr_percentile,
            bb_width_percentile,
        )

        ########################################################################
        # EMA STRUCTURE AND SLOPE
        ########################################################################

        ema50_slope = self._normalized_slope(
            frame["EMA_50"],
            close,
        )

        ema200_slope = self._normalized_slope(
            frame["EMA_200"],
            close,
        )

        bullish_alignment = (
            ema20 > ema50 > ema200
        )

        bearish_alignment = (
            ema20 < ema50 < ema200
        )

        ema20_50_spread = abs(
            ema20 - ema50
        ) / max(abs(close), 1e-12)

        ema50_200_spread = abs(
            ema50 - ema200
        ) / max(abs(close), 1e-12)

        ########################################################################
        # TREND SCORE
        ########################################################################

        trend_score = 0.0
        bullish_points = 0.0
        bearish_points = 0.0

        if bullish_alignment:
            trend_score += 35.0
            bullish_points += 35.0
            reasons.append("Bullish EMA alignment")

        elif bearish_alignment:
            trend_score += 35.0
            bearish_points += 35.0
            reasons.append("Bearish EMA alignment")

        else:
            reasons.append("EMA alignment is mixed")

        if adx >= self.adx_trend_threshold:
            adx_bonus = min(
                30.0,
                15.0
                + (
                    adx - self.adx_trend_threshold
                )
                * 1.5,
            )

            trend_score += adx_bonus

            reasons.append(
                f"ADX confirms trend strength ({adx:.1f})"
            )

        elif adx >= self.adx_range_threshold:
            trend_score += 6.0

            reasons.append(
                f"ADX shows developing trend strength ({adx:.1f})"
            )

        if ema50_slope > 0 and ema200_slope >= 0:
            trend_score += 20.0
            bullish_points += 20.0

            reasons.append("EMA slopes are rising")

        elif ema50_slope < 0 and ema200_slope <= 0:
            trend_score += 20.0
            bearish_points += 20.0

            reasons.append("EMA slopes are falling")

        elif ema50_slope > 0:
            trend_score += 8.0
            bullish_points += 8.0

            reasons.append("Medium-term EMA slope is rising")

        elif ema50_slope < 0:
            trend_score += 8.0
            bearish_points += 8.0

            reasons.append("Medium-term EMA slope is falling")

        if close > ema20:
            bullish_points += 10.0

        elif close < ema20:
            bearish_points += 10.0

        if ema20_50_spread >= 0.001:
            trend_score += 10.0

            reasons.append(
                "Short and medium EMAs are sufficiently separated"
            )

        if ema50_200_spread >= 0.002:
            trend_score += 5.0

        trend_score = min(
            trend_score,
            100.0,
        )

        ########################################################################
        # DIRECTION
        ########################################################################

        direction_difference = (
            bullish_points - bearish_points
        )

        if direction_difference >= 10:
            direction = "BULLISH"

        elif direction_difference <= -10:
            direction = "BEARISH"

        else:
            direction = "NEUTRAL"

        ########################################################################
        # RANGE SCORE
        ########################################################################

        range_score = 0.0

        if adx <= self.adx_range_threshold:
            range_score += 40.0

            reasons.append(
                f"ADX indicates weak trend ({adx:.1f})"
            )

        elif adx < self.adx_trend_threshold:
            range_score += 15.0

        if bb_width_percentile <= 20:
            range_score += 35.0

            reasons.append(
                "Bollinger Bands are strongly compressed"
            )

        elif bb_width_percentile <= 35:
            range_score += 25.0

            reasons.append(
                "Bollinger Bands are moderately compressed"
            )

        if abs(ema50_slope) < 0.0003:
            range_score += 20.0

            reasons.append(
                "Medium-term EMA is relatively flat"
            )

        elif abs(ema50_slope) < 0.0005:
            range_score += 10.0

        if not bullish_alignment and not bearish_alignment:
            range_score += 10.0

        range_score = min(
            range_score,
            100.0,
        )

        ########################################################################
        # BREAKOUT SCORE
        ########################################################################

        prior = frame.iloc[
            -(self.breakout_lookback + 1):-1
        ]

        if "high" in prior.columns:
            prior_high = float(
                pd.to_numeric(
                    prior["high"],
                    errors="coerce",
                ).max()
            )
        else:
            prior_high = float(
                pd.to_numeric(
                    prior["close"],
                    errors="coerce",
                ).max()
            )

        if "low" in prior.columns:
            prior_low = float(
                pd.to_numeric(
                    prior["low"],
                    errors="coerce",
                ).min()
            )
        else:
            prior_low = float(
                pd.to_numeric(
                    prior["close"],
                    errors="coerce",
                ).min()
            )

        breakout_up = (
            close > prior_high
            and previous_close <= prior_high
        )

        breakout_down = (
            close < prior_low
            and previous_close >= prior_low
        )

        breakout_score = 0.0

        if breakout_up:
            breakout_score += 55.0
            direction = "BULLISH"

            reasons.append(
                "Price broke above the recent trading range"
            )

        elif breakout_down:
            breakout_score += 55.0
            direction = "BEARISH"

            reasons.append(
                "Price broke below the recent trading range"
            )

        if bb_width_percentile >= 85:
            breakout_score += 25.0

            reasons.append(
                "Strong Bollinger Band expansion"
            )

        elif bb_width_percentile >= 70:
            breakout_score += 20.0

            reasons.append(
                "Bollinger Band expansion supports breakout"
            )

        if atr_percentile >= 85:
            breakout_score += 20.0

            reasons.append(
                "Strong ATR expansion supports breakout"
            )

        elif atr_percentile >= 70:
            breakout_score += 15.0

            reasons.append(
                "ATR expansion supports breakout"
            )

        if adx >= self.adx_trend_threshold:
            breakout_score += 10.0

        breakout_score = min(
            breakout_score,
            100.0,
        )

                ########################################################################
        # FINAL REGIME CLASSIFICATION
        ########################################################################

        if (
            breakout_score >= 70
        ):

            regime = REGIME_BREAKOUT

            winning_score = breakout_score

        elif (
            volatility_score >= 85
            and trend_score < 65
        ):

            regime = REGIME_HIGH_VOLATILITY

            winning_score = volatility_score

        elif (
            trend_score >= 60
            and direction == "BULLISH"
        ):

            regime = REGIME_TREND_UP

            winning_score = trend_score

        elif (
            trend_score >= 60
            and direction == "BEARISH"
        ):

            regime = REGIME_TREND_DOWN

            winning_score = trend_score

        elif range_score >= 55:

            regime = REGIME_RANGE

            winning_score = range_score

        elif volatility_score <= 20:

            regime = REGIME_LOW_VOLATILITY

            winning_score = 100 - volatility_score

            reasons.append(
                "ATR and Bollinger Bands indicate very low volatility"
            )

        else:

            regime = REGIME_RANGE

            winning_score = max(
                range_score,
                40.0,
            )

            reasons.append(
                "No regime reached confirmation threshold"
            )

        ########################################################################
        # MARKET BIAS
        ########################################################################

        if regime == REGIME_TREND_UP:

            if trend_score >= 85:

                market_bias = "STRONG_BULLISH"

            else:

                market_bias = "BULLISH"

        elif regime == REGIME_TREND_DOWN:

            if trend_score >= 85:

                market_bias = "STRONG_BEARISH"

            else:

                market_bias = "BEARISH"

        elif regime == REGIME_BREAKOUT:

            if direction == "BULLISH":

                market_bias = "BULLISH_BREAKOUT"

            elif direction == "BEARISH":

                market_bias = "BEARISH_BREAKOUT"

            else:

                market_bias = "BREAKOUT"

        elif regime == REGIME_RANGE:

            market_bias = "SIDEWAYS"

        elif regime == REGIME_HIGH_VOLATILITY:

            market_bias = "HIGH_VOLATILITY"

        elif regime == REGIME_LOW_VOLATILITY:

            market_bias = "LOW_VOLATILITY"

        else:

            market_bias = "NEUTRAL"

        ########################################################################
        # RISK MULTIPLIER
        ########################################################################

        if regime == REGIME_TREND_UP:

            risk_multiplier = 1.00

        elif regime == REGIME_TREND_DOWN:

            risk_multiplier = 1.00

        elif regime == REGIME_BREAKOUT:

            risk_multiplier = 0.80

        elif regime == REGIME_RANGE:

            risk_multiplier = 0.50

        elif regime == REGIME_HIGH_VOLATILITY:

            risk_multiplier = 0.30

        elif regime == REGIME_LOW_VOLATILITY:

            risk_multiplier = 0.00

        else:

            risk_multiplier = 0.00

        ########################################################################
        # CONFIDENCE
        ########################################################################

        competing_scores = sorted(
            [
                trend_score,
                range_score,
                breakout_score,
            ],
            reverse=True,
        )

        if len(competing_scores) > 1:

            margin = (
                competing_scores[0]
                - competing_scores[1]
            )

        else:

            margin = competing_scores[0]

        confidence = max(
            0.0,
            min(
                100.0,
                (0.70 * winning_score)
                + (0.30 * margin),
            ),
        )

        ########################################################################
        # REMOVE DUPLICATE REASONS
        ########################################################################

        unique_reasons = []

        for reason in reasons:

            if reason not in unique_reasons:

                unique_reasons.append(reason)

        ########################################################################
        # RETURN RESULT
        ########################################################################

        return RegimeResult(

            regime=regime,

            confidence=round(
                confidence,
                1,
            ),

            trend_score=round(
                trend_score,
                1,
            ),

            range_score=round(
                range_score,
                1,
            ),

            breakout_score=round(
                breakout_score,
                1,
            ),

            volatility_score=round(
                volatility_score,
                1,
            ),

            direction=direction,

            market_bias=market_bias,

            risk_multiplier=risk_multiplier,

            reasons=tuple(
                unique_reasons[-8:]
            ),

        ).to_dict()

            ############################################################################
    # SIGNAL VALIDATION
    ############################################################################

    def allows_signal(
        self,
        regime: dict[str, Any],
        signal: str,
    ) -> tuple[bool, str]:

        signal = signal.upper().strip()

        regime_name = str(
            regime.get(
                "regime",
                REGIME_UNKNOWN,
            )
        )

        direction = str(
            regime.get(
                "direction",
                "NEUTRAL",
            )
        )

        confidence = float(
            regime.get(
                "confidence",
                0.0,
            )
        )

        risk_multiplier = float(
            regime.get(
                "risk_multiplier",
                0.0,
            )
        )

        ####################################################################
        # HOLD
        ####################################################################

        if signal == "HOLD":

            return (
                True,
                "No trade requested.",
            )

        ####################################################################
        # UNKNOWN
        ####################################################################

        if regime_name == REGIME_UNKNOWN:

            return (
                False,
                "Unknown market regime.",
            )

        ####################################################################
        # LOW VOLATILITY
        ####################################################################

        if regime_name == REGIME_LOW_VOLATILITY:

            return (
                False,
                "Market volatility is too low.",
            )

        ####################################################################
        # HIGH VOLATILITY
        ####################################################################

        if regime_name == REGIME_HIGH_VOLATILITY:

            return (
                False,
                "Market volatility is too high.",
            )

        ####################################################################
        # CONFIDENCE FILTER
        ####################################################################

        if confidence < 45:

            return (
                False,
                "Regime confidence is too low.",
            )

        ####################################################################
        # RISK FILTER
        ####################################################################

        if risk_multiplier <= 0:

            return (
                False,
                "Risk multiplier blocks trading.",
            )

        ####################################################################
        # TREND FILTERS
        ####################################################################

        if (
            regime_name == REGIME_TREND_UP
            and signal == "SELL"
        ):

            return (
                False,
                "SELL opposes bullish trend.",
            )

        if (
            regime_name == REGIME_TREND_DOWN
            and signal == "BUY"
        ):

            return (
                False,
                "BUY opposes bearish trend.",
            )

        ####################################################################
        # BREAKOUT FILTERS
        ####################################################################

        if regime_name == REGIME_BREAKOUT:

            expected = (
                "BUY"
                if direction == "BULLISH"
                else "SELL"
            )

            if signal != expected:

                return (
                    False,
                    f"{signal} conflicts with breakout direction.",
                )

        ####################################################################
        # RANGE
        ####################################################################

        if regime_name == REGIME_RANGE:

            return (
                True,
                "Range market detected. Mean-reversion strategies recommended.",
            )

        ####################################################################
        # DEFAULT
        ####################################################################

        return (
            True,
            f"{signal} is compatible with {regime_name}.",
        )