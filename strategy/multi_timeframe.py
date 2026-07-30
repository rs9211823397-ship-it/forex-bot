from __future__ import annotations

from typing import Any

import math
import pandas as pd

from indicators.technical import TechnicalIndicators
from price_action.candles import CandlePatterns


class MultiTimeframeAnalyzer:
    """
    Analyze higher-timeframe trend and lower-timeframe entry alignment.

    The analyzer combines:

    - EMA structure
    - EMA slope
    - ADX trend strength
    - RSI momentum
    - MACD momentum
    - Lower-timeframe candle patterns
    - Lower-timeframe EMA direction

    Backward-compatible output keys:

    - higher_trend
    - confirmation
    """

    REQUIRED_COLUMNS = {
        "close",
        "EMA_20",
        "EMA_50",
        "EMA_200",
    }

    BULLISH_PATTERNS = {
        "bullish engulfing",
        "bullish pin bar",
        "strong bullish candle",
        "hammer",
        "morning star",
    }

    BEARISH_PATTERNS = {
        "bearish engulfing",
        "bearish pin bar",
        "strong bearish candle",
        "shooting star",
        "evening star",
    }

    def __init__(
        self,
        *,
        minimum_confirmation_score: float = 60.0,
        strong_confirmation_score: float = 80.0,
        adx_trend_threshold: float = 20.0,
        slope_lookback: int = 5,
    ) -> None:
        self.indicators = TechnicalIndicators()
        self.candles = CandlePatterns()

        self.minimum_confirmation_score = float(
            minimum_confirmation_score
        )
        self.strong_confirmation_score = float(
            strong_confirmation_score
        )
        self.adx_trend_threshold = float(
            adx_trend_threshold
        )
        self.slope_lookback = int(
            slope_lookback
        )

    ###########################################################################
    # PUBLIC METHODS
    ###########################################################################

    def get_trend(self, df: pd.DataFrame) -> str:
        """
        Return only the higher-timeframe direction.

        This method is retained for backward compatibility.
        """

        result = self.get_trend_details(df)

        return str(
            result.get(
                "trend",
                "SIDEWAYS",
            )
        )

    def get_trend_details(
        self,
        df: pd.DataFrame,
    ) -> dict[str, Any]:
        """
        Analyze higher-timeframe market direction and strength.
        """

        prepared = self._prepare_dataframe(df)

        if prepared.empty:
            return self._empty_trend_result(
                "No usable higher-timeframe data"
            )

        latest = prepared.iloc[-1]

        close = self._safe_float(
            latest.get("close")
        )

        ema20 = self._safe_float(
            latest.get("EMA_20")
        )

        ema50 = self._safe_float(
            latest.get("EMA_50")
        )

        ema200 = self._safe_float(
            latest.get("EMA_200")
        )

        adx = self._safe_float(
            latest.get("ADX")
        )

        rsi = self._safe_float(
            latest.get("RSI"),
            default=50.0,
        )

        macd = self._safe_float(
            latest.get("MACD")
        )

        macd_signal = self._safe_float(
            latest.get("MACD_SIGNAL")
        )

        bullish_score = 0.0
        bearish_score = 0.0

        reasons: list[str] = []
        warnings: list[str] = []

        #######################################################################
        # EMA ALIGNMENT
        #######################################################################

        bullish_alignment = (
            ema20 > ema50 > ema200
        )

        bearish_alignment = (
            ema20 < ema50 < ema200
        )

        if bullish_alignment:
            bullish_score += 40.0

            reasons.append(
                "Higher-timeframe EMAs are bullish"
            )

        elif bearish_alignment:
            bearish_score += 40.0

            reasons.append(
                "Higher-timeframe EMAs are bearish"
            )

        else:
            warnings.append(
                "Higher-timeframe EMA structure is mixed"
            )

        #######################################################################
        # PRICE LOCATION
        #######################################################################

        if close > ema20:
            bullish_score += 10.0

            reasons.append(
                "Price is above EMA 20"
            )

        elif close < ema20:
            bearish_score += 10.0

            reasons.append(
                "Price is below EMA 20"
            )

        #######################################################################
        # EMA SLOPES
        #######################################################################

        ema50_slope = self._normalized_slope(
            prepared["EMA_50"],
            close,
        )

        ema200_slope = self._normalized_slope(
            prepared["EMA_200"],
            close,
        )

        if (
            ema50_slope > 0
            and ema200_slope >= 0
        ):
            bullish_score += 20.0

            reasons.append(
                "Higher-timeframe EMA slopes are rising"
            )

        elif (
            ema50_slope < 0
            and ema200_slope <= 0
        ):
            bearish_score += 20.0

            reasons.append(
                "Higher-timeframe EMA slopes are falling"
            )

        else:
            warnings.append(
                "Higher-timeframe EMA slopes are not aligned"
            )

        #######################################################################
        # ADX
        #######################################################################

        if adx >= 35:
            if bullish_score > bearish_score:
                bullish_score += 15.0

            elif bearish_score > bullish_score:
                bearish_score += 15.0

            reasons.append(
                f"ADX shows strong trend strength ({adx:.1f})"
            )

        elif adx >= self.adx_trend_threshold:
            if bullish_score > bearish_score:
                bullish_score += 10.0

            elif bearish_score > bullish_score:
                bearish_score += 10.0

            reasons.append(
                f"ADX confirms trend strength ({adx:.1f})"
            )

        else:
            warnings.append(
                f"ADX is weak ({adx:.1f})"
            )

        #######################################################################
        # RSI
        #######################################################################

        if rsi >= 55:
            bullish_score += 8.0

            reasons.append(
                f"RSI supports bullish momentum ({rsi:.1f})"
            )

        elif rsi <= 45:
            bearish_score += 8.0

            reasons.append(
                f"RSI supports bearish momentum ({rsi:.1f})"
            )

        else:
            warnings.append(
                f"RSI is neutral ({rsi:.1f})"
            )

        #######################################################################
        # MACD
        #######################################################################

        if macd > macd_signal:
            bullish_score += 7.0

            reasons.append(
                "MACD supports bullish momentum"
            )

        elif macd < macd_signal:
            bearish_score += 7.0

            reasons.append(
                "MACD supports bearish momentum"
            )

        #######################################################################
        # FINAL HIGHER-TIMEFRAME TREND
        #######################################################################

        bullish_score = min(
            bullish_score,
            100.0,
        )

        bearish_score = min(
            bearish_score,
            100.0,
        )

        difference = (
            bullish_score
            - bearish_score
        )

        if (
            bullish_score >= 50
            and difference >= 15
        ):
            trend = "BULLISH"
            trend_score = bullish_score

        elif (
            bearish_score >= 50
            and difference <= -15
        ):
            trend = "BEARISH"
            trend_score = bearish_score

        else:
            trend = "SIDEWAYS"
            trend_score = max(
                bullish_score,
                bearish_score,
            )

        strength = self._strength_label(
            trend_score
        )

        confidence = self._directional_confidence(
            bullish_score,
            bearish_score,
        )

        return {
            "trend": trend,
            "strength": strength,
            "confidence": round(
                confidence,
                1,
            ),
            "trend_score": round(
                trend_score,
                1,
            ),
            "bullish_score": round(
                bullish_score,
                1,
            ),
            "bearish_score": round(
                bearish_score,
                1,
            ),
            "adx": round(
                adx,
                2,
            ),
            "rsi": round(
                rsi,
                2,
            ),
            "ema50_slope": round(
                ema50_slope,
                6,
            ),
            "ema200_slope": round(
                ema200_slope,
                6,
            ),
            "reasons": self._unique(
                reasons
            ),
            "warnings": self._unique(
                warnings
            ),
        }

    def analyze(
        self,
        higher_tf: pd.DataFrame,
        lower_tf: pd.DataFrame,
    ) -> dict[str, Any]:
        """
        Confirm whether the lower-timeframe setup aligns with the
        higher-timeframe market direction.
        """

        higher_result = self.get_trend_details(
            higher_tf
        )

        higher_trend = str(
            higher_result.get(
                "trend",
                "SIDEWAYS",
            )
        )

        higher_confidence = float(
            higher_result.get(
                "confidence",
                0.0,
            )
        )

        lower = self._prepare_dataframe(
            lower_tf
        )

        if lower.empty:
            return self._empty_analysis_result(
                higher_result,
                "No usable lower-timeframe data",
            )

        latest = lower.iloc[-1]

        patterns = self._get_patterns(
            lower
        )

        normalized_patterns = {
            str(pattern).strip().lower()
            for pattern in patterns
        }

        bullish_pattern = self._contains_pattern(
            normalized_patterns,
            self.BULLISH_PATTERNS,
        )

        bearish_pattern = self._contains_pattern(
            normalized_patterns,
            self.BEARISH_PATTERNS,
        )

        bullish_score = 0.0
        bearish_score = 0.0

        reasons: list[str] = []
        warnings: list[str] = []

        #######################################################################
        # HIGHER-TIMEFRAME DIRECTION
        #######################################################################

        if higher_trend == "BULLISH":
            bullish_score += 40.0

            reasons.append(
                "Higher timeframe is bullish"
            )

        elif higher_trend == "BEARISH":
            bearish_score += 40.0

            reasons.append(
                "Higher timeframe is bearish"
            )

        else:
            warnings.append(
                "Higher timeframe is sideways"
            )

        #######################################################################
        # LOWER-TIMEFRAME CANDLE PATTERNS
        #######################################################################

        if bullish_pattern:
            bullish_score += 25.0

            reasons.append(
                "Lower timeframe has a bullish candle pattern"
            )

        if bearish_pattern:
            bearish_score += 25.0

            reasons.append(
                "Lower timeframe has a bearish candle pattern"
            )

        if bullish_pattern and bearish_pattern:
            warnings.append(
                "Conflicting candle patterns detected"
            )

        #######################################################################
        # LOWER-TIMEFRAME EMA STRUCTURE
        #######################################################################

        close = self._safe_float(
            latest.get("close")
        )

        ema20 = self._safe_float(
            latest.get("EMA_20")
        )

        ema50 = self._safe_float(
            latest.get("EMA_50")
        )

        ema200 = self._safe_float(
            latest.get("EMA_200")
        )

        if ema20 > ema50:
            bullish_score += 12.0

            reasons.append(
                "Lower-timeframe EMA structure is bullish"
            )

        elif ema20 < ema50:
            bearish_score += 12.0

            reasons.append(
                "Lower-timeframe EMA structure is bearish"
            )

        if close > ema20:
            bullish_score += 8.0

        elif close < ema20:
            bearish_score += 8.0

        if ema50 > ema200:
            bullish_score += 5.0

        elif ema50 < ema200:
            bearish_score += 5.0

        #######################################################################
        # LOWER-TIMEFRAME MOMENTUM
        #######################################################################

        rsi = self._safe_float(
            latest.get("RSI"),
            default=50.0,
        )

        macd = self._safe_float(
            latest.get("MACD")
        )

        macd_signal = self._safe_float(
            latest.get("MACD_SIGNAL")
        )

        if rsi >= 55:
            bullish_score += 5.0

            reasons.append(
                "Lower-timeframe RSI is bullish"
            )

        elif rsi <= 45:
            bearish_score += 5.0

            reasons.append(
                "Lower-timeframe RSI is bearish"
            )

        if macd > macd_signal:
            bullish_score += 5.0

            reasons.append(
                "Lower-timeframe MACD is bullish"
            )

        elif macd < macd_signal:
            bearish_score += 5.0

            reasons.append(
                "Lower-timeframe MACD is bearish"
            )

        #######################################################################
        # SCORE NORMALIZATION
        #######################################################################

        bullish_score = min(
            bullish_score,
            100.0,
        )

        bearish_score = min(
            bearish_score,
            100.0,
        )

        #######################################################################
        # CONFLICT DETECTION
        #######################################################################

        conflict = False
        conflict_reason = ""

        if (
            higher_trend == "BULLISH"
            and bearish_score > bullish_score
        ):
            conflict = True

            conflict_reason = (
                "Lower timeframe conflicts with bullish higher timeframe"
            )

        elif (
            higher_trend == "BEARISH"
            and bullish_score > bearish_score
        ):
            conflict = True

            conflict_reason = (
                "Lower timeframe conflicts with bearish higher timeframe"
            )

        elif higher_trend == "SIDEWAYS":
            conflict = True

            conflict_reason = (
                "Higher timeframe has no confirmed direction"
            )

        if conflict_reason:
            warnings.append(
                conflict_reason
            )

        #######################################################################
        # FINAL CONFIRMATION
        #######################################################################

        confirmation = "HOLD"
        confirmed = False
        alignment_score = 0.0

        if (
            not conflict
            and higher_trend == "BULLISH"
            and bullish_score >= self.minimum_confirmation_score
            and bullish_score > bearish_score
        ):
            confirmation = "BUY"
            confirmed = True
            alignment_score = bullish_score

        elif (
            not conflict
            and higher_trend == "BEARISH"
            and bearish_score >= self.minimum_confirmation_score
            and bearish_score > bullish_score
        ):
            confirmation = "SELL"
            confirmed = True
            alignment_score = bearish_score

        else:
            alignment_score = max(
                bullish_score,
                bearish_score,
            )

            if alignment_score < self.minimum_confirmation_score:
                warnings.append(
                    "Multi-timeframe confirmation score is too low"
                )

        #######################################################################
        # FINAL CONFIDENCE
        #######################################################################

        confidence = (
            0.60 * alignment_score
            + 0.40 * higher_confidence
        )

        if conflict:
            confidence *= 0.50

        confidence = max(
            0.0,
            min(
                100.0,
                confidence,
            ),
        )

        strength = self._strength_label(
            confidence
        )

        return {
            # Backward compatibility
            "higher_trend": higher_trend,
            "confirmation": confirmation,

            # Enhanced output
            "confirmed": confirmed,
            "confidence": round(
                confidence,
                1,
            ),
            "strength": strength,
            "alignment_score": round(
                alignment_score,
                1,
            ),
            "bullish_score": round(
                bullish_score,
                1,
            ),
            "bearish_score": round(
                bearish_score,
                1,
            ),
            "conflict": conflict,
            "patterns": patterns,
            "reasons": self._unique(
                reasons
            ),
            "warnings": self._unique(
                warnings
            ),
            "higher_timeframe": higher_result,
            "lower_timeframe": {
                "rsi": round(
                    rsi,
                    2,
                ),
                "macd": round(
                    macd,
                    6,
                ),
                "macd_signal": round(
                    macd_signal,
                    6,
                ),
                "close": round(
                    close,
                    6,
                ),
            },
        }

    ###########################################################################
    # INTERNAL HELPERS
    ###########################################################################

    def _prepare_dataframe(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Validate, copy and enrich a dataframe with technical indicators.
        """

        if not isinstance(
            df,
            pd.DataFrame,
        ):
            return pd.DataFrame()

        if df.empty:
            return pd.DataFrame()

        try:
            prepared = df.copy()

            prepared = self.indicators.add_indicators(
                prepared
            )

        except Exception:
            return pd.DataFrame()

        prepared = prepared.replace(
            [math.inf, -math.inf],
            pd.NA,
        )

        missing = self.REQUIRED_COLUMNS.difference(
            prepared.columns
        )

        if missing:
            return pd.DataFrame()

        prepared = prepared.dropna(
            subset=list(
                self.REQUIRED_COLUMNS
            )
        )

        return prepared

    def _get_patterns(
        self,
        df: pd.DataFrame,
    ) -> list[str]:
        """
        Safely retrieve candle patterns regardless of whether the candle
        analyzer returns a list, tuple, set, string or dictionary.
        """

        try:
            result = self.candles.analyze(
                df
            )

        except Exception:
            return []

        if result is None:
            return []

        if isinstance(
            result,
            str,
        ):
            return [result]

        if isinstance(
            result,
            dict,
        ):
            patterns: list[str] = []

            for key, value in result.items():
                if isinstance(
                    value,
                    bool,
                ) and value:
                    patterns.append(
                        str(key)
                    )

                elif isinstance(
                    value,
                    str,
                ):
                    patterns.append(
                        value
                    )

                elif isinstance(
                    value,
                    (list, tuple, set),
                ):
                    patterns.extend(
                        str(item)
                        for item in value
                    )

            return self._unique(
                patterns
            )

        if isinstance(
            result,
            (list, tuple, set),
        ):
            return self._unique(
                [
                    str(item)
                    for item in result
                ]
            )

        return [
            str(result)
        ]

    def _normalized_slope(
        self,
        series: pd.Series,
        close: float,
    ) -> float:
        values = pd.to_numeric(
            series,
            errors="coerce",
        ).dropna()

        if len(values) <= self.slope_lookback:
            return 0.0

        previous_value = float(
            values.iloc[
                -1 - self.slope_lookback
            ]
        )

        current_value = float(
            values.iloc[-1]
        )

        return (
            current_value
            - previous_value
        ) / max(
            abs(close),
            1e-12,
        )

    @staticmethod
    def _contains_pattern(
        detected_patterns: set[str],
        accepted_patterns: set[str],
    ) -> bool:
        for detected in detected_patterns:
            for accepted in accepted_patterns:
                if accepted in detected:
                    return True

        return False

    @staticmethod
    def _safe_float(
        value: Any,
        *,
        default: float = 0.0,
    ) -> float:
        try:
            result = float(
                value
            )

            if not math.isfinite(
                result
            ):
                return default

            return result

        except (
            TypeError,
            ValueError,
        ):
            return default

    @staticmethod
    def _directional_confidence(
        bullish_score: float,
        bearish_score: float,
    ) -> float:
        winning_score = max(
            bullish_score,
            bearish_score,
        )

        margin = abs(
            bullish_score
            - bearish_score
        )

        return max(
            0.0,
            min(
                100.0,
                0.70 * winning_score
                + 0.30 * margin,
            ),
        )

    def _strength_label(
        self,
        score: float,
    ) -> str:
        if score >= 90:
            return "VERY_STRONG"

        if score >= self.strong_confirmation_score:
            return "STRONG"

        if score >= self.minimum_confirmation_score:
            return "MODERATE"

        if score >= 40:
            return "WEAK"

        return "VERY_WEAK"

    @staticmethod
    def _unique(
        values: list[str],
    ) -> list[str]:
        output: list[str] = []

        for value in values:
            normalized = str(
                value
            ).strip()

            if (
                normalized
                and normalized not in output
            ):
                output.append(
                    normalized
                )

        return output

    @staticmethod
    def _empty_trend_result(
        reason: str,
    ) -> dict[str, Any]:
        return {
            "trend": "SIDEWAYS",
            "strength": "VERY_WEAK",
            "confidence": 0.0,
            "trend_score": 0.0,
            "bullish_score": 0.0,
            "bearish_score": 0.0,
            "adx": 0.0,
            "rsi": 50.0,
            "ema50_slope": 0.0,
            "ema200_slope": 0.0,
            "reasons": [],
            "warnings": [reason],
        }

    @staticmethod
    def _empty_analysis_result(
        higher_result: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "higher_trend": str(
                higher_result.get(
                    "trend",
                    "SIDEWAYS",
                )
            ),
            "confirmation": "HOLD",
            "confirmed": False,
            "confidence": 0.0,
            "strength": "VERY_WEAK",
            "alignment_score": 0.0,
            "bullish_score": 0.0,
            "bearish_score": 0.0,
            "conflict": True,
            "patterns": [],
            "reasons": [],
            "warnings": [reason],
            "higher_timeframe": higher_result,
            "lower_timeframe": {},
        }