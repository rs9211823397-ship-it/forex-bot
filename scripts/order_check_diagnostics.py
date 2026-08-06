#!/usr/bin/env python3
"""No-send broker compatibility diagnostic for all active MT5 symbols.

Calls MT5 order_check for BUY and SELL requests but never calls order_send. This
validates broker filling mode, normalized volume, stop/target validity, margin,
current tick freshness, and the same risk-budget sizing used by live demo entry.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

from scripts.sizing_diagnostics import atr14


def main() -> None:
    from config.settings import (
        EXECUTION_MODE,
        MT5_EXPECTED_LOGIN,
        MT5_LOGIN,
        MT5_MAX_OPEN_POSITIONS,
        MT5_MAX_SPREAD_STOP_RATIO,
        MT5_MAX_TICK_AGE_SECONDS,
        MT5_PASSWORD,
        MT5_SERVER,
        MT5_SYMBOL_MAP,
        MT5_TERMINAL_PATH,
        RISK_PERCENT,
        TRADING_TIMEFRAME,
    )
    from data.market_data import MarketData
    from execution.mt5_executor import ExecutionConfig, MT5Executor

    print("[ordercheck] READ ONLY: order_check WILL run; order_send WILL NOT run")
    if EXECUTION_MODE != "MT5_DEMO":
        raise SystemExit("[ordercheck] ERROR: AAQTS_EXECUTION_MODE must be MT5_DEMO")
    if not MT5_EXPECTED_LOGIN:
        raise SystemExit("[ordercheck] ERROR: MT5 identity is not pinned; run scripts/pin_mt5_account.py")

    executor = MT5Executor(
        ExecutionConfig(
            terminal_path=MT5_TERMINAL_PATH,
            login=int(MT5_LOGIN) if MT5_LOGIN else None,
            expected_login=int(MT5_EXPECTED_LOGIN),
            password=MT5_PASSWORD,
            server=MT5_SERVER,
            max_open_positions=MT5_MAX_OPEN_POSITIONS,
            max_tick_age_seconds=MT5_MAX_TICK_AGE_SECONDS,
            max_spread_stop_ratio=MT5_MAX_SPREAD_STOP_RATIO,
        )
    )
    executor.connect()
    try:
        account = executor.account_snapshot()
        risk_budget = account.equity * RISK_PERCENT / 100.0
        frames = MarketData(cache_downloads=False).download_all_data(interval=TRADING_TIMEFRAME)
        passed = 0
        failed = 0
        checks = 0

        for source in sorted(MT5_SYMBOL_MAP):
            broker = MT5_SYMBOL_MAP[source]
            frame = frames.get(source)
            if frame is None or frame.empty:
                failed += 2
                print(f"[ordercheck] {source:10s} -> {broker:10s} | ERROR | no fresh candles")
                continue
            stop_distance = 1.5 * atr14(frame)
            info = executor.symbol_info(broker)
            tick = executor.symbol_tick(broker)

            for side in ("BUY", "SELL"):
                checks += 1
                try:
                    is_buy = side == "BUY"
                    price = float(tick.ask if is_buy else tick.bid)
                    stop = price - stop_distance if is_buy else price + stop_distance
                    target = price + 2.0 * stop_distance if is_buy else price - 2.0 * stop_distance
                    executor._validate_protection(side, price, stop, target, info)
                    executor._validate_tick_and_spread(tick, price, stop)
                    volume = executor._volume_for_risk(
                        symbol=broker,
                        side=side,
                        entry=price,
                        stop_loss=stop,
                        risk_amount=risk_budget,
                        info=info,
                    )
                    volume = executor._normalize_volume(volume, info)
                    order_type = executor.mt5.ORDER_TYPE_BUY if is_buy else executor.mt5.ORDER_TYPE_SELL
                    request = {
                        "action": executor.mt5.TRADE_ACTION_DEAL,
                        "symbol": broker,
                        "volume": volume,
                        "type": order_type,
                        "price": executor._round_price(price, info),
                        "sl": executor._round_price(stop, info),
                        "tp": executor._round_price(target, info),
                        "deviation": executor.config.deviation,
                        "magic": executor.config.magic,
                        "comment": f"AAQTS CHECK {source}"[:31],
                        "type_time": executor.mt5.ORDER_TIME_GTC,
                        "type_filling": executor._filling_mode(info),
                    }
                    check = executor.mt5.order_check(request)
                    retcode = getattr(check, "retcode", None) if check is not None else None
                    if check is None or retcode != 0:
                        detail = getattr(check, "comment", executor.mt5.last_error())
                        raise RuntimeError(f"order_check retcode={retcode} detail={detail}")
                    margin = executor.mt5.order_calc_margin(order_type, broker, volume, price)
                    margin_text = "n/a" if margin is None else f"${float(margin):.2f}"
                    passed += 1
                    print(
                        f"[ordercheck] {source:10s} -> {broker:10s} | {side:4s} | PASS | "
                        f"volume={volume:g} risk_budget=${risk_budget:.2f} margin={margin_text}"
                    )
                except Exception as exc:
                    failed += 1
                    print(f"[ordercheck] {source:10s} -> {broker:10s} | {side:4s} | FAIL | {type(exc).__name__}: {exc}")

        print(f"[ordercheck] SUMMARY | symbols={len(MT5_SYMBOL_MAP)} checks={checks} passed={passed} failed={failed}")
        if failed:
            raise SystemExit(1)
    finally:
        executor.shutdown()


if __name__ == "__main__":
    main()
