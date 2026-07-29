"""Fail-closed validation functions for the signal pipeline."""

import numpy as np
import pandas as pd

from strategy.decision import ValidationResult


STRATEGY_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "VOL_SMA20",
    "OBV",
    "ADX",
    "EMA_20",
    "EMA_50",
    "EMA_200",
    "SUPERTREND",
    "MACD",
    "MACD_SIGNAL",
    "RSI",
    "STOCH_RSI"
)


def _timestamp_values(data):
    close_time_column = next(
        (
            column
            for column in data.columns
            if str(column).lower() == "close_time"
        ),
        None
    )

    if close_time_column is not None:
        return pd.to_datetime(
            data[close_time_column],
            utc=True,
            errors="coerce"
        )

    if isinstance(data.index, pd.DatetimeIndex):
        return pd.Series(
            pd.to_datetime(data.index, utc=True),
            index=data.index
        )

    return None


def validate_input_frame(data):
    """Validate frame shape and causal timestamp ordering before selection."""

    if not isinstance(data, pd.DataFrame):
        return ValidationResult(
            valid=False,
            reasons=("Invalid market data: expected DataFrame",)
        )

    if data.empty:
        return ValidationResult(
            valid=False,
            reasons=("Invalid market data: no candles",)
        )

    timestamps = _timestamp_values(data)

    if timestamps is not None:
        if timestamps.isna().any():
            return ValidationResult(
                valid=False,
                reasons=("Invalid market data: invalid timestamp",)
            )

        if timestamps.duplicated().any():
            return ValidationResult(
                valid=False,
                reasons=("Invalid market data: duplicate timestamps",)
            )

        if not timestamps.is_monotonic_increasing:
            return ValidationResult(
                valid=False,
                reasons=(
                    "Invalid market data: timestamps not monotonic",
                )
            )

    if "ADX" not in data.columns:
        return ValidationResult(
            valid=False,
            reasons=("Invalid market data: missing ADX",)
        )

    return ValidationResult(valid=True)


def validate_strategy_features(data):
    """Validate all columns consumed after the ADX eligibility gate."""

    missing = [
        column
        for column in STRATEGY_COLUMNS
        if column not in data.columns
    ]

    if missing:
        return ValidationResult(
            valid=False,
            reasons=(
                "Invalid market data: missing "
                + ", ".join(missing),
            )
        )

    latest = data.iloc[-1]
    numeric_columns = tuple(
        column
        for column in STRATEGY_COLUMNS
        if column != "SUPERTREND"
    )
    numeric_values = pd.to_numeric(
        latest.loc[list(numeric_columns)],
        errors="coerce"
    ).to_numpy(dtype=float)

    if not np.isfinite(numeric_values).all():
        return ValidationResult(
            valid=False,
            reasons=(
                "Invalid market data: non-finite strategy feature",
            )
        )

    if pd.isna(latest["SUPERTREND"]):
        return ValidationResult(
            valid=False,
            reasons=(
                "Invalid market data: non-finite strategy feature",
            )
        )

    if (
        latest["high"] < max(latest["open"], latest["close"])
        or latest["low"] > min(latest["open"], latest["close"])
        or latest["high"] < latest["low"]
    ):
        return ValidationResult(
            valid=False,
            reasons=("Invalid market data: invalid OHLC",)
        )

    if len(data) > 1 and not np.isfinite(
        pd.to_numeric(
            data.iloc[-2]["OBV"],
            errors="coerce"
        )
    ):
        return ValidationResult(
            valid=False,
            reasons=("Invalid market data: non-finite prior OBV",)
        )

    return ValidationResult(valid=True)


def validate_data(data):
    """
    Select the latest row using the legacy access contract.

    Deliberately do not add new column, length, type, or NaN policies here:
    doing so would change which inputs the existing ``SignalEngine`` accepts
    and which exceptions it raises.
    """

    return data.iloc[-1]


def validate_market_regime(latest):
    """Apply the existing ADX market-regime gate without changing its rule."""

    try:
        adx = float(latest["ADX"])
    except (KeyError, TypeError, ValueError):
        return ValidationResult(
            valid=False,
            reasons=("Weak market (ADX below 25)",)
        )

    # Preserve the historical boundary at 35.0: values below that are weak.
    if adx < 35.0:
        return ValidationResult(
            valid=False,
            reasons=("Weak market (ADX below 25)",)
        )

    return ValidationResult(valid=True)


def validate_risk():
    """
    Preserve the legacy signal-layer risk behavior.

    The pre-refactor ``SignalEngine`` did not perform risk validation. Risk is
    handled after signal generation by ``RiskManager``. This explicit
    pass-through stage keeps that production boundary unchanged.
    """

    return ValidationResult(valid=True)
