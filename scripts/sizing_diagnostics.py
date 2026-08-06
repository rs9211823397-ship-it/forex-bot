#!/usr/bin/env python3
"""Read-only MT5 sizing diagnostics for small-account compatibility.

The script never calls order_check or order_send. It reads the connected demo
account, broker symbol metadata/ticks, and completed MT5 candles. For each
approved source symbol it estimates a representative stop using 1.5x 14-period
ATR on the configured trading timeframe, then reports whether the broker's
minimum lot can stay within the configured per-trade risk budget.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


def atr14(frame: pd.DataFrame) -> float:
    """Return a causal 14-period ATR estimate from completed candles."""
    if frame is None or len(frame) < 15:
        raise ValueError("at least 15 completed candles are required")
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    previous_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    value = float(tr.rolling(14, min_periods=14).mean().iloc[-1])
    if not math.isfinite(value) or value <= 0:
        raise ValueError("ATR is unavailable or non-positive")
    return value


def classify_min_lot_risk(min_lot_risk: float, risk_budget: float) -> tuple[str, float]:
    """Classify whether broker minimum volume respects the risk budget."""
    if not math.isfinite(min_lot_risk) or min_lot_risk < 0:
        raise ValueError("min_lot_risk must be finite and non-negative")
    if not math.isfinite(risk_budget) or risk_budget <= 0:
        raise ValueError("risk_budget must be finite and positive")
    ratio = min_lot_risk / risk_budget
    return ("EXECUTABLE" if ratio <= 1.0 + 1e-9 else "TOO_SMALL_FOR_MIN_LOT", ratio)


def main() -> None:
    from config.settings import (
        EXECUTION_MODE,
        MT5_EXPECTED_LOGIN,
        MT5_LOGIN,
        MT5_PASSWORD,
        MT5_SERVER,
        MT5_SYMBOL_MAP,
        MT5_TERMINAL_PATH,
        RISK_PERCENT,
        TRADING_TIMEFRAME,
    )
    from data.market_data import MarketData
    from execution.mt5_executor import ExecutionConfig, ExecutionError, MT5Executor

    print("[sizing] READ ONLY: no order_check/order_send will be called")
    if EXECUTION_MODE != "MT5_DEMO":
        raise SystemExit("[sizing] ERROR: run with AAQTS_EXECUTION_MODE=MT5_DEMO")

    executor = MT5Executor(
        ExecutionConfig(
            terminal_path=MT5_TERMINAL_PATH,
            login=int(MT5_LOGIN) if MT5_LOGIN else None,
            expected_login=int(MT5_EXPECTED_LOGIN) if MT5_EXPECTED_LOGIN else None,
            password=MT5_PASSWORD,
            server=MT5_SERVER,
        )
    )
    executor.connect()
    try:
        account = executor.account_snapshot()
        risk_budget = float(account.equity) * float(RISK_PERCENT) / 100.0
        print(
            f"[sizing] account equity={account.equity:.2f} risk_percent={RISK_PERCENT:.2f}% "
            f"base_risk_budget=${risk_budget:.2f} timeframe={TRADING_TIMEFRAME}"
        )

        market = MarketData()
        frames = market.download_all_data(interval=TRADING_TIMEFRAME)
        executable = 0
        blocked = 0
        failures = 0

        for source in sorted(MT5_SYMBOL_MAP):
            broker = MT5_SYMBOL_MAP[source]
            try:
                frame = frames.get(source)
                if frame is None or frame.empty:
                    raise ValueError("fresh completed MT5 candles unavailable")
                atr = atr14(frame)
                stop_distance = atr * 1.5

                info = executor.symbol_info(broker)
                tick = executor.symbol_tick(broker)
                min_volume = float(getattr(info, "volume_min", 0.0) or 0.0)
                if min_volume <= 0:
                    raise ValueError("broker minimum volume is unavailable")

                bid = float(getattr(tick, "bid", 0.0) or 0.0)
                ask = float(getattr(tick, "ask", 0.0) or 0.0)
                if bid <= 0 or ask <= 0 or ask < bid:
                    raise ValueError("invalid executable quote")

                buy_loss = executor.mt5.order_calc_profit(
                    executor.mt5.ORDER_TYPE_BUY,
                    broker,
                    min_volume,
                    ask,
                    ask - stop_distance,
                )
                sell_loss = executor.mt5.order_calc_profit(
                    executor.mt5.ORDER_TYPE_SELL,
                    broker,
                    min_volume,
                    bid,
                    bid + stop_distance,
                )
                if buy_loss is None or sell_loss is None:
                    raise ExecutionError(f"order_calc_profit unavailable for {broker}: {executor.mt5.last_error()}")
                min_lot_risk = max(-float(buy_loss), -float(sell_loss), 0.0)
                status, ratio = classify_min_lot_risk(min_lot_risk, risk_budget)
                if status == "EXECUTABLE":
                    executable += 1
                else:
                    blocked += 1

                spread = ask - bid
                print(
                    f"[sizing] {source:10s} -> {broker:10s} | {status:21s} | "
                    f"min_lot={min_volume:g} atr14={atr:.8g} stop~1.5ATR={stop_distance:.8g} "
                    f"min_lot_risk=${min_lot_risk:.2f} budget=${risk_budget:.2f} "
                    f"risk/budget={ratio:.2f}x spread={spread:.8g}"
                )
            except Exception as exc:
                failures += 1
                print(f"[sizing] {source:10s} -> {broker:10s} | ERROR | {type(exc).__name__}: {exc}")

        print(
            f"[sizing] SUMMARY | symbols={len(MT5_SYMBOL_MAP)} executable={executable} "
            f"too_small_for_min_lot={blocked} failures={failures}"
        )
        if failures:
            raise SystemExit(1)
    finally:
        executor.shutdown()


if __name__ == "__main__":
    main()
