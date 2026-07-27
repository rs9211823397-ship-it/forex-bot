"""Causal, explainable market-regime classification.

The classifier deliberately keeps trend and volatility as separate
dimensions.  A market is always classified as either ``TRENDING`` or
``RANGING`` and, independently, as ``HIGH_VOLATILITY``,
``NORMAL_VOLATILITY``, or ``LOW_VOLATILITY``.  ``regime`` provides a
deterministic primary label for callers that require one value.

All features are recomputed after the point-in-time candle selection.  This
prevents precomputed indicator columns, including accidentally centered
rolling calculations, from introducing future information.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite

import numpy as np
import pandas as pd

from data.timeframes import (
    TimeframeError,
    normalize_timestamp,
    select_closed_candles,
)


TRENDING = "TRENDING"
RANGING = "RANGING"
HIGH_VOLATILITY = "HIGH_VOLATILITY"
NORMAL_VOLATILITY = "NORMAL_VOLATILITY"
LOW_VOLATILITY = "LOW_VOLATILITY"

BULLISH = "BULLISH"
BEARISH = "BEARISH"
NEUTRAL = "NEUTRAL"


class MarketRegimeError(ValueError):
    """Raised when a causal market-regime classification cannot be made."""


@dataclass(frozen=True)
class MarketRegimeConfig:
    """Explicit, research-stable classifier parameters.

    Defaults use conventional indicator periods and intentionally are not
    inferred or optimized from the input dataset.
    """

    ema_fast_period: int = 20
    ema_medium_period: int = 50
    ema_slow_period: int = 200
    atr_period: int = 14
    adx_period: int = 14
    realized_volatility_period: int = 20
    volatility_baseline_period: int = 60
    minimum_history: int = 200
    adx_trend_threshold: float = 25.0
    minimum_ema_separation_atr: float = 0.25
    high_volatility_ratio: float = 1.50
    low_volatility_ratio: float = 0.75

    def __post_init__(self):
        periods = {
            "ema_fast_period": self.ema_fast_period,
            "ema_medium_period": self.ema_medium_period,
            "ema_slow_period": self.ema_slow_period,
            "atr_period": self.atr_period,
            "adx_period": self.adx_period,
            "realized_volatility_period": (
                self.realized_volatility_period
            ),
            "volatility_baseline_period": (
                self.volatility_baseline_period
            ),
            "minimum_history": self.minimum_history,
        }

        for name, value in periods.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise MarketRegimeError(
                    f"{name} must be a positive integer"
                )

        if not (
            self.ema_fast_period
            < self.ema_medium_period
            < self.ema_slow_period
        ):
            raise MarketRegimeError(
                "EMA periods must satisfy fast < medium < slow"
            )

        positive_thresholds = {
            "adx_trend_threshold": self.adx_trend_threshold,
            "minimum_ema_separation_atr": (
                self.minimum_ema_separation_atr
            ),
            "high_volatility_ratio": self.high_volatility_ratio,
            "low_volatility_ratio": self.low_volatility_ratio,
        }

        for name, value in positive_thresholds.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
                or value <= 0
            ):
                raise MarketRegimeError(
                    f"{name} must be a positive finite number"
                )

        if self.low_volatility_ratio >= 1.0:
            raise MarketRegimeError(
                "low_volatility_ratio must be below 1"
            )

        if self.high_volatility_ratio <= 1.0:
            raise MarketRegimeError(
                "high_volatility_ratio must be above 1"
            )


@dataclass(frozen=True)
class RegimeComponents:
    """Point-in-time component values supporting a classification."""

    adx: float
    atr: float
    atr_percent: float
    atr_baseline_percent: float
    atr_ratio: float
    realized_volatility: float
    realized_volatility_baseline: float
    realized_volatility_ratio: float
    volatility_ratio: float
    ema_fast: float
    ema_medium: float
    ema_slow: float
    ema_separation_atr: float


@dataclass(frozen=True)
class MarketRegimeClassification:
    """Immutable and explainable market-regime output."""

    regime: str
    trend_state: str
    volatility_state: str
    direction: str
    decision_time: pd.Timestamp
    candle_close_time: pd.Timestamp
    candles_used: int
    components: RegimeComponents
    reason_codes: tuple[str, ...]

    @property
    def active_regimes(self):
        """Return both orthogonal regime dimensions."""

        return (self.trend_state, self.volatility_state)

    def to_dict(self):
        """Return a serialization-friendly explanation dictionary."""

        result = asdict(self)
        result["decision_time"] = self.decision_time.isoformat()
        result["candle_close_time"] = (
            self.candle_close_time.isoformat()
        )
        result["active_regimes"] = list(self.active_regimes)
        result["reason_codes"] = list(self.reason_codes)
        return result


class MarketRegimeClassifier:
    """Classify a timestamped OHLC frame using only closed candles."""

    _REQUIRED_COLUMNS = ("open", "high", "low", "close")
    _RATIO_EPSILON = 1e-12

    def __init__(self, config=None):
        self.config = config or MarketRegimeConfig()

        if not isinstance(self.config, MarketRegimeConfig):
            raise TypeError(
                "config must be a MarketRegimeConfig"
            )

    def classify(
        self,
        data,
        decision_time,
        timeframe=None,
    ):
        """Return the causal regime at ``decision_time``.

        ``data`` must expose an explicit ``close_time`` column or a
        ``DatetimeIndex`` from which close times can be derived.  Candles with
        close times after the decision are excluded before any indicator is
        calculated.
        """

        if not isinstance(data, pd.DataFrame):
            raise MarketRegimeError(
                "Market-regime data must be a pandas DataFrame"
            )

        try:
            decision = normalize_timestamp(
                decision_time,
                "decision_time",
            )
            historical = select_closed_candles(
                data,
                decision,
                timeframe,
            )
        except TimeframeError as exc:
            raise MarketRegimeError(str(exc)) from exc

        self._validate_historical_data(historical)
        required = self.required_history

        if len(historical) < required:
            raise MarketRegimeError(
                "Insufficient closed-candle history: "
                f"received {len(historical)}, require {required}"
            )

        features = self._calculate_features(historical)
        latest = features.iloc[-1]
        components = self._components(latest)
        (
            trend_state,
            direction,
            trend_reasons,
        ) = self._classify_trend(components)
        (
            volatility_state,
            volatility_reasons,
        ) = self._classify_volatility(components)

        if volatility_state == HIGH_VOLATILITY:
            primary = HIGH_VOLATILITY
        elif volatility_state == LOW_VOLATILITY:
            primary = LOW_VOLATILITY
        else:
            primary = trend_state

        return MarketRegimeClassification(
            regime=primary,
            trend_state=trend_state,
            volatility_state=volatility_state,
            direction=direction,
            decision_time=decision,
            candle_close_time=historical["close_time"].iloc[-1],
            candles_used=len(historical),
            components=components,
            reason_codes=tuple(
                trend_reasons + volatility_reasons
            ),
        )

    @property
    def required_history(self):
        """Minimum rows required for every configured rolling component."""

        config = self.config
        return max(
            config.minimum_history,
            config.ema_slow_period,
            (2 * config.adx_period) - 1,
            (
                config.atr_period
                + config.volatility_baseline_period
            ),
            (
                config.realized_volatility_period
                + config.volatility_baseline_period
                + 1
            ),
        )

    def _validate_historical_data(self, data):
        missing = [
            column
            for column in self._REQUIRED_COLUMNS
            if column not in data.columns
        ]

        if missing:
            raise MarketRegimeError(
                "Missing OHLC columns: " + ", ".join(missing)
            )

        if data.empty:
            raise MarketRegimeError(
                "No closed candles are available at decision_time"
            )

        try:
            numeric = data.loc[
                :,
                self._REQUIRED_COLUMNS,
            ].astype(float)
        except (TypeError, ValueError) as exc:
            raise MarketRegimeError(
                "OHLC values must be numeric"
            ) from exc

        values = numeric.to_numpy()

        if not np.isfinite(values).all():
            raise MarketRegimeError(
                "Closed-candle OHLC values must be finite"
            )

        if (numeric["close"] <= 0).any():
            raise MarketRegimeError(
                "Close prices must be positive"
            )

        invalid = (
            (numeric["high"] < numeric["low"])
            | (
                numeric["high"]
                < numeric[["open", "close"]].max(axis=1)
            )
            | (
                numeric["low"]
                > numeric[["open", "close"]].min(axis=1)
            )
        )

        if invalid.any():
            raise MarketRegimeError(
                "Invalid closed-candle OHLC relationships"
            )

    def _calculate_features(self, data):
        config = self.config
        features = data.loc[
            :,
            ["open", "high", "low", "close"],
        ].astype(float).copy()

        features["ema_fast"] = features["close"].ewm(
            span=config.ema_fast_period,
            adjust=False,
        ).mean()
        features["ema_medium"] = features["close"].ewm(
            span=config.ema_medium_period,
            adjust=False,
        ).mean()
        features["ema_slow"] = features["close"].ewm(
            span=config.ema_slow_period,
            adjust=False,
        ).mean()

        previous_close = features["close"].shift(1)
        true_range = pd.concat(
            (
                features["high"] - features["low"],
                (features["high"] - previous_close).abs(),
                (features["low"] - previous_close).abs(),
            ),
            axis=1,
        ).max(axis=1)
        features["atr"] = true_range.rolling(
            config.atr_period,
            min_periods=config.atr_period,
        ).mean()

        up_move = features["high"].diff()
        down_move = -features["low"].diff()
        plus_dm = up_move.where(
            (up_move > down_move) & (up_move > 0),
            0.0,
        )
        minus_dm = down_move.where(
            (down_move > up_move) & (down_move > 0),
            0.0,
        )
        directional_atr = true_range.rolling(
            config.adx_period,
            min_periods=config.adx_period,
        ).mean()
        plus_di = 100.0 * (
            plus_dm.rolling(
                config.adx_period,
                min_periods=config.adx_period,
            ).mean()
            / directional_atr
        )
        minus_di = 100.0 * (
            minus_dm.rolling(
                config.adx_period,
                min_periods=config.adx_period,
            ).mean()
            / directional_atr
        )
        directional_sum = plus_di + minus_di
        dx = (
            100.0
            * (plus_di - minus_di).abs()
            / directional_sum.replace(0.0, np.nan)
        ).where(directional_sum != 0.0, 0.0)
        features["adx"] = dx.rolling(
            config.adx_period,
            min_periods=config.adx_period,
        ).mean()

        features["atr_percent"] = (
            features["atr"] / features["close"]
        )
        features["atr_baseline_percent"] = (
            features["atr_percent"]
            .shift(1)
            .rolling(
                config.volatility_baseline_period,
                min_periods=config.volatility_baseline_period,
            )
            .median()
        )

        log_returns = np.log(features["close"]).diff()
        features["realized_volatility"] = log_returns.rolling(
            config.realized_volatility_period,
            min_periods=config.realized_volatility_period,
        ).std(ddof=0)
        features["realized_volatility_baseline"] = (
            features["realized_volatility"]
            .shift(1)
            .rolling(
                config.volatility_baseline_period,
                min_periods=config.volatility_baseline_period,
            )
            .median()
        )

        latest_index = features.index[-1]
        features.loc[latest_index, "atr_ratio"] = (
            self._relative_ratio(
                features["atr_percent"].iloc[-1],
                features["atr_baseline_percent"].iloc[-1],
            )
        )
        features.loc[
            latest_index,
            "realized_volatility_ratio",
        ] = self._relative_ratio(
            features["realized_volatility"].iloc[-1],
            features["realized_volatility_baseline"].iloc[-1],
        )
        features.loc[latest_index, "volatility_ratio"] = (
            (
                features["atr_ratio"].iloc[-1]
                + features["realized_volatility_ratio"].iloc[-1]
            )
            / 2.0
        )

        first_gap = (
            features["ema_fast"].iloc[-1]
            - features["ema_medium"].iloc[-1]
        )
        second_gap = (
            features["ema_medium"].iloc[-1]
            - features["ema_slow"].iloc[-1]
        )
        features.loc[latest_index, "ema_separation_atr"] = (
            min(abs(first_gap), abs(second_gap))
            / features["atr"].iloc[-1]
        )
        return features

    def _relative_ratio(self, current, baseline):
        if not isfinite(float(current)):
            raise MarketRegimeError(
                "Current volatility component is unavailable"
            )

        if not isfinite(float(baseline)):
            raise MarketRegimeError(
                "Historical volatility baseline is unavailable"
            )

        if baseline <= self._RATIO_EPSILON:
            if current <= self._RATIO_EPSILON:
                return 1.0
            return self.config.high_volatility_ratio + 1.0

        return float(current / baseline)

    @staticmethod
    def _components(latest):
        names = (
            "adx",
            "atr",
            "atr_percent",
            "atr_baseline_percent",
            "atr_ratio",
            "realized_volatility",
            "realized_volatility_baseline",
            "realized_volatility_ratio",
            "volatility_ratio",
            "ema_fast",
            "ema_medium",
            "ema_slow",
            "ema_separation_atr",
        )
        values = {
            name: float(latest[name])
            for name in names
        }

        if not all(isfinite(value) for value in values.values()):
            raise MarketRegimeError(
                "Regime components must all be finite"
            )

        return RegimeComponents(**values)

    def _classify_trend(self, components):
        bullish_alignment = (
            components.ema_fast
            > components.ema_medium
            > components.ema_slow
        )
        bearish_alignment = (
            components.ema_fast
            < components.ema_medium
            < components.ema_slow
        )
        strong_adx = (
            components.adx
            >= self.config.adx_trend_threshold
        )
        separated = (
            components.ema_separation_atr
            >= self.config.minimum_ema_separation_atr
        )

        reasons = []

        if strong_adx:
            reasons.append("ADX_TREND_STRENGTH")
        else:
            reasons.append("ADX_BELOW_TREND_THRESHOLD")

        if bullish_alignment:
            reasons.append("EMA_BULLISH_ALIGNMENT")
        elif bearish_alignment:
            reasons.append("EMA_BEARISH_ALIGNMENT")
        else:
            reasons.append("EMA_NOT_ALIGNED")

        if separated:
            reasons.append("EMA_SEPARATION_CONFIRMED")
        else:
            reasons.append("EMA_SEPARATION_WEAK")

        if strong_adx and separated and (
            bullish_alignment or bearish_alignment
        ):
            reasons.append("REGIME_TRENDING")
            direction = (
                BULLISH
                if bullish_alignment
                else BEARISH
            )
            return TRENDING, direction, reasons

        reasons.append("REGIME_RANGING")
        return RANGING, NEUTRAL, reasons

    def _classify_volatility(self, components):
        ratio = components.volatility_ratio

        if ratio >= self.config.high_volatility_ratio:
            return HIGH_VOLATILITY, ["VOLATILITY_EXPANSION"]

        if ratio <= self.config.low_volatility_ratio:
            return LOW_VOLATILITY, ["VOLATILITY_COMPRESSION"]

        return NORMAL_VOLATILITY, ["VOLATILITY_NORMAL"]
