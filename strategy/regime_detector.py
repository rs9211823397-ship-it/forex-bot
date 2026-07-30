"""Deterministic market-regime classification for AAQTS.

The detector consumes an indicator-enriched OHLC dataframe and returns a
transparent score-based classification.  It deliberately avoids future data:
all features are calculated from rows available at the decision candle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import math
import pandas as pd


REGIME_TREND_UP = "TREND_UP"
REGIME_TREND_DOWN = "TREND_DOWN"
REGIME_RANGE = "RANGE"
REGIME_BREAKOUT = "BREAKOUT"
REGIME_HIGH_VOLATILITY = "HIGH_VOLATILITY"
REGIME_LOW_VOLATILITY = "LOW_VOLATILITY"
REGIME_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RegimeResult:
    regime: str
    confidence: float
    trend_score: float
    range_score: float
    breakout_score: float
    volatility_score: float
    direction: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        return result


class MarketRegimeDetector:
    """Classify the latest completed candle into a practical trading regime."""

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
    ) -> None:
        self.adx_trend_threshold = float(adx_trend_threshold)
        self.adx_range_threshold = float(adx_range_threshold)
        self.lookback = int(lookback)
        self.slope_lookback = int(slope_lookback)
        self.breakout_lookback = int(breakout_lookback)

    def detect(self, data: pd.DataFrame) -> dict[str, Any]:
        self._validate(data)
        clean = data.replace([math.inf, -math.inf], pd.NA).dropna(
            subset=list(self.REQUIRED_COLUMNS)
        )
        minimum_rows = max(self.slope_lookback + 1, self.breakout_lookback + 1, 30)
        if len(clean) < minimum_rows:
            return RegimeResult(
                regime=REGIME_UNKNOWN,
                confidence=0.0,
                trend_score=0.0,
                range_score=0.0,
                breakout_score=0.0,
                volatility_score=0.0,
                direction="NEUTRAL",
                reasons=(f"Insufficient regime history ({len(clean)}/{minimum_rows})",),
            ).to_dict()

        frame = clean.iloc[-self.lookback :].copy()
        latest = frame.iloc[-1]
        previous = frame.iloc[-2]

        close = float(latest["close"])
        adx = float(latest["ADX"])
        atr_pct = self._percentile_rank(frame["ATR"], float(latest["ATR"]))

        bb_width = self._bb_width(frame)
        current_bb_width = float(bb_width.iloc[-1])
        bb_width_pct = self._percentile_rank(bb_width, current_bb_width)

        ema50_slope = self._normalized_slope(frame["EMA_50"], close)
        ema200_slope = self._normalized_slope(frame["EMA_200"], close)

        bullish_alignment = (
            float(latest["EMA_20"]) > float(latest["EMA_50"]) > float(latest["EMA_200"])
        )
        bearish_alignment = (
            float(latest["EMA_20"]) < float(latest["EMA_50"]) < float(latest["EMA_200"])
        )

        direction = "NEUTRAL"
        trend_score = 0.0
        reasons: list[str] = []

        if bullish_alignment:
            trend_score += 35
            direction = "BULLISH"
            reasons.append("Bullish EMA alignment")
        elif bearish_alignment:
            trend_score += 35
            direction = "BEARISH"
            reasons.append("Bearish EMA alignment")

        if adx >= self.adx_trend_threshold:
            trend_score += min(30.0, (adx - self.adx_trend_threshold) * 1.5 + 15.0)
            reasons.append(f"ADX confirms trend strength ({adx:.1f})")

        if ema50_slope > 0 and ema200_slope >= 0:
            trend_score += 20
            direction = "BULLISH" if direction == "NEUTRAL" else direction
            reasons.append("EMA slopes are rising")
        elif ema50_slope < 0 and ema200_slope <= 0:
            trend_score += 20
            direction = "BEARISH" if direction == "NEUTRAL" else direction
            reasons.append("EMA slopes are falling")

        ema_spread = abs(float(latest["EMA_20"]) - float(latest["EMA_50"])) / max(abs(close), 1e-12)
        if ema_spread >= 0.001:
            trend_score += 15

        range_score = 0.0
        if adx <= self.adx_range_threshold:
            range_score += 40
            reasons.append(f"ADX indicates weak trend ({adx:.1f})")
        if bb_width_pct <= 35:
            range_score += 30
            reasons.append("Bollinger width is compressed")
        if abs(ema50_slope) < 0.0005:
            range_score += 20
        if not bullish_alignment and not bearish_alignment:
            range_score += 10

        prior = frame.iloc[-(self.breakout_lookback + 1) : -1]
        prior_high = float(prior["high"].max()) if "high" in prior else float(prior["close"].max())
        prior_low = float(prior["low"].min()) if "low" in prior else float(prior["close"].min())
        previous_close = float(previous["close"])
        breakout_up = close > prior_high and previous_close <= prior_high
        breakout_down = close < prior_low and previous_close >= prior_low

        breakout_score = 0.0
        if breakout_up or breakout_down:
            breakout_score += 55
            direction = "BULLISH" if breakout_up else "BEARISH"
            reasons.append("Price broke the recent trading range")
        if bb_width_pct >= 70:
            breakout_score += 20
            reasons.append("Bollinger width is expanding")
        if atr_pct >= 70:
            breakout_score += 15
            reasons.append("ATR expansion supports breakout")
        if adx >= self.adx_trend_threshold:
            breakout_score += 10

        volatility_score = max(atr_pct, bb_width_pct)

        if breakout_score >= 70:
            regime = REGIME_BREAKOUT
            winning_score = breakout_score
        elif volatility_score >= 85 and trend_score < 65:
            regime = REGIME_HIGH_VOLATILITY
            winning_score = volatility_score
        elif trend_score >= 60 and direction == "BULLISH":
            regime = REGIME_TREND_UP
            winning_score = trend_score
        elif trend_score >= 60 and direction == "BEARISH":
            regime = REGIME_TREND_DOWN
            winning_score = trend_score
        elif range_score >= 55:
            regime = REGIME_RANGE
            winning_score = range_score
        elif volatility_score <= 20:
            regime = REGIME_LOW_VOLATILITY
            winning_score = 100 - volatility_score
            reasons.append("ATR and Bollinger width are unusually low")
        else:
            regime = REGIME_RANGE
            winning_score = max(range_score, 40.0)
            reasons.append("No directional regime reached confirmation threshold")

        competing = sorted([trend_score, range_score, breakout_score], reverse=True)
        margin = competing[0] - competing[1] if len(competing) > 1 else competing[0]
        confidence = max(0.0, min(100.0, 0.7 * winning_score + 0.3 * margin))

        return RegimeResult(
            regime=regime,
            confidence=round(confidence, 1),
            trend_score=round(trend_score, 1),
            range_score=round(range_score, 1),
            breakout_score=round(breakout_score, 1),
            volatility_score=round(volatility_score, 1),
            direction=direction,
            reasons=tuple(reasons[-6:]),
        ).to_dict()

    def allows_signal(self, regime: dict[str, Any], signal: str) -> tuple[bool, str]:
        signal = signal.upper().strip()
        name = str(regime.get("regime", REGIME_UNKNOWN))
        direction = str(regime.get("direction", "NEUTRAL"))

        if signal == "HOLD":
            return True, "No directional trade requested"
        if name == REGIME_UNKNOWN:
            return False, "Regime is unknown"
        if name == REGIME_LOW_VOLATILITY:
            return False, "Low-volatility regime blocks new entries"
        if name == REGIME_HIGH_VOLATILITY:
            return False, "Unstructured high-volatility regime blocks new entries"
        if name == REGIME_TREND_UP and signal == "SELL":
            return False, "SELL conflicts with TREND_UP regime"
        if name == REGIME_TREND_DOWN and signal == "BUY":
            return False, "BUY conflicts with TREND_DOWN regime"
        if name == REGIME_BREAKOUT and direction in {"BULLISH", "BEARISH"}:
            expected = "BUY" if direction == "BULLISH" else "SELL"
            if signal != expected:
                return False, f"{signal} conflicts with {direction.lower()} breakout"
        return True, f"{signal} is compatible with {name}"

    def _validate(self, data: pd.DataFrame) -> None:
        if not isinstance(data, pd.DataFrame) or data.empty:
            raise ValueError("Regime detector requires a non-empty pandas DataFrame")
        missing = self.REQUIRED_COLUMNS.difference(data.columns)
        if missing:
            raise ValueError(f"Missing regime columns: {', '.join(sorted(missing))}")

    def _normalized_slope(self, series: pd.Series, close: float) -> float:
        values = pd.to_numeric(series, errors="coerce").dropna()
        if len(values) <= self.slope_lookback:
            return 0.0
        return (float(values.iloc[-1]) - float(values.iloc[-1 - self.slope_lookback])) / max(
            abs(close), 1e-12
        )

    @staticmethod
    def _bb_width(frame: pd.DataFrame) -> pd.Series:
        middle = pd.to_numeric(frame["BB_MIDDLE"], errors="coerce").abs().replace(0, pd.NA)
        return (
            pd.to_numeric(frame["BB_UPPER"], errors="coerce")
            - pd.to_numeric(frame["BB_LOWER"], errors="coerce")
        ) / middle

    @staticmethod
    def _percentile_rank(series: pd.Series, value: float) -> float:
        values = pd.to_numeric(series, errors="coerce").dropna()
        if values.empty:
            return 50.0
        return float((values <= value).mean() * 100.0)
