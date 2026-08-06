#!/usr/bin/env python3
"""Read-only AAQTS runtime diagnostics.

This script exercises the live market-data -> indicators -> regime router ->
strategy decision path for every active symbol and, in MT5_DEMO, validates the
connected broker account and mapped quotes.  It never calls order_check or
order_send and therefore cannot place a trade.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)


def _reason_text(decision: dict) -> str:
    reasons = [str(item).strip() for item in decision.get("reasons", ()) if str(item).strip()]
    return " | ".join(reasons) if reasons else "none"


def _broker_check() -> None:
    from config.settings import (
        EXECUTION_MODE,
        MT5_EXPECTED_LOGIN,
        MT5_LOGIN,
        MT5_PASSWORD,
        MT5_SERVER,
        MT5_SYMBOL_MAP,
        MT5_TERMINAL_PATH,
    )

    if EXECUTION_MODE != "MT5_DEMO":
        print(f"[diag] Broker execution mode: {EXECUTION_MODE}")
        return

    from execution.mt5_executor import ExecutionConfig, MT5Executor

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
        positions = executor.positions(managed_only=True)
        quoted = 0
        unavailable = []
        for source, broker in MT5_SYMBOL_MAP.items():
            try:
                tick = executor.symbol_tick(broker)
                bid = float(getattr(tick, "bid", 0.0) or 0.0)
                ask = float(getattr(tick, "ask", 0.0) or 0.0)
                if bid > 0 and ask >= bid:
                    quoted += 1
                else:
                    unavailable.append(f"{source}->{broker}")
            except Exception:
                unavailable.append(f"{source}->{broker}")
        pin_state = "PINNED" if (MT5_EXPECTED_LOGIN or MT5_LOGIN) else "TERMINAL_SESSION"
        print(
            f"[diag] MT5 account OK | balance={account.balance:.2f} "
            f"equity={account.equity:.2f} managed_positions={len(positions)} "
            f"quotes={quoted}/{len(MT5_SYMBOL_MAP)} identity={pin_state}"
        )
        if unavailable:
            print("[diag] Unavailable broker quotes: " + ", ".join(unavailable))
    finally:
        executor.shutdown()


def main() -> None:
    from config.settings import HIGHER_TIMEFRAME, TRADING_TIMEFRAME
    from data.market_data import MarketData
    from indicators.technical import TechnicalIndicators
    from strategy.regime_router import RegimeStrategyRouter
    from strategy.signal_engine import SignalEngine

    print("[diag] READ ONLY: no order_check/order_send will be called")
    _broker_check()

    market = MarketData()
    indicators = TechnicalIndicators()
    engine = SignalEngine.production(
        higher_timeframe=HIGHER_TIMEFRAME,
        lower_timeframe=TRADING_TIMEFRAME,
    )
    router = RegimeStrategyRouter(
        engine,
        higher_timeframe=HIGHER_TIMEFRAME,
        lower_timeframe=TRADING_TIMEFRAME,
    )

    lower = market.download_all_data(interval=TRADING_TIMEFRAME)
    higher = market.download_all_data(interval=HIGHER_TIMEFRAME)
    symbols = sorted(lower)
    buy_sell = 0
    holds = 0
    failures = 0

    for symbol in symbols:
        try:
            analyzed = indicators.add_indicators(lower[symbol])
            decision = router.generate_analysis(analyzed, symbol, higher.get(symbol))
            signal = str(decision.get("signal", "HOLD"))
            if signal in {"BUY", "SELL"}:
                buy_sell += 1
            else:
                holds += 1
            print(
                f"[diag] {symbol} | signal={signal} "
                f"trade_conf={decision.get('confidence', 0)} "
                f"strategy={decision.get('strategy', 'UNKNOWN')} "
                f"regime={decision.get('regime', 'UNKNOWN')} "
                f"regime_conf={decision.get('regime_confidence', 0)} "
                f"htf={decision.get('higher_timeframe_regime', 'UNKNOWN')}"
            )
            print(f"       reasons={_reason_text(decision)}")
        except Exception as exc:
            failures += 1
            print(f"[diag] {symbol} | ERROR | {type(exc).__name__}: {exc}")

    missing_higher = sorted(set(symbols).difference(higher))
    if missing_higher:
        print("[diag] Missing higher-timeframe frames: " + ", ".join(missing_higher))

    print(
        f"[diag] SUMMARY | symbols={len(symbols)} actionable={buy_sell} "
        f"holds={holds} failures={failures}"
    )
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
