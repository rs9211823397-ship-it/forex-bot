"""Supertrend indicator implementation optimized for live multi-asset scans."""

import numpy as np
import pandas as pd


def add_supertrend(df, period=10, multiplier=3):
    """Add a boolean SUPERTREND column without slow per-row pandas indexing.

    The calculation is recursive, so a small NumPy loop is retained, but all
    expensive ``Series.iloc`` reads/writes are removed. This makes the
    indicator suitable for repeated multi-symbol and multi-timeframe scans.
    """

    result = df.copy()

    if isinstance(result.columns, pd.MultiIndex):
        result.columns = result.columns.get_level_values(0)

    result = result.loc[:, ~result.columns.duplicated()].copy()

    required = {"high", "low", "close", "ATR"}
    missing = required.difference(result.columns)
    if missing:
        result["SUPERTREND"] = True
        return result

    if result.empty:
        result["SUPERTREND"] = pd.Series(dtype=bool, index=result.index)
        return result

    high = pd.to_numeric(result["high"], errors="coerce").to_numpy(dtype=float)
    low = pd.to_numeric(result["low"], errors="coerce").to_numpy(dtype=float)
    close = pd.to_numeric(result["close"], errors="coerce").to_numpy(dtype=float)
    atr = pd.to_numeric(result["ATR"], errors="coerce").to_numpy(dtype=float)

    hl2 = (high + low) / 2.0
    upper = hl2 + (float(multiplier) * atr)
    lower = hl2 - (float(multiplier) * atr)

    final_upper = upper.copy()
    final_lower = lower.copy()
    supertrend = np.ones(len(result), dtype=bool)

    for i in range(1, len(result)):
        previous_upper = final_upper[i - 1]
        previous_lower = final_lower[i - 1]
        current_close = close[i]

        if np.isnan(current_close) or np.isnan(previous_upper) or np.isnan(previous_lower):
            supertrend[i] = supertrend[i - 1]
            continue

        if current_close > previous_upper:
            supertrend[i] = True
        elif current_close < previous_lower:
            supertrend[i] = False
        else:
            supertrend[i] = supertrend[i - 1]

            if supertrend[i]:
                if not np.isnan(final_lower[i]):
                    final_lower[i] = max(final_lower[i], previous_lower)
            else:
                if not np.isnan(final_upper[i]):
                    final_upper[i] = min(final_upper[i], previous_upper)

    result["SUPERTREND"] = supertrend
    return result
