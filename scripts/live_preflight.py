#!/usr/bin/env python3
"""Read-only preflight for AAQTS MT5_LIVE. Never calls order_check/order_send."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
os.chdir(REPO_ROOT)

LOGIN_FILE = REPO_ROOT / "runtime" / "mt5_live_expected_login.txt"
SERVER_FILE = REPO_ROOT / "runtime" / "mt5_live_expected_server.txt"
BASELINE_FILE = REPO_ROOT / "runtime" / "mt5_live_risk_baseline_utc.txt"
ACK = "I_UNDERSTAND_REAL_MONEY"


def fail(message: str) -> None:
    print(f"[live-preflight] ERROR: {message}")
    raise SystemExit(1)


def main() -> None:
    print("[live-preflight] READ ONLY: no order_check/order_send will be called")
    if os.getenv("AAQTS_EXECUTION_MODE", "").upper().strip() != "MT5_LIVE":
        fail("AAQTS_EXECUTION_MODE must be MT5_LIVE")
    if os.getenv("AAQTS_LIVE_TRADING_ACK", "").strip() != ACK:
        fail("live release acknowledgement is missing")
    if not LOGIN_FILE.is_file() or not SERVER_FILE.is_file():
        fail("live account identity is not pinned")
    if not BASELINE_FILE.is_file():
        fail("live risk baseline is not initialized")

    expected_login = LOGIN_FILE.read_text(encoding="utf-8").strip()
    expected_server = SERVER_FILE.read_text(encoding="utf-8").strip()
    if not expected_login.isdigit() or not expected_server:
        fail("live pin files are invalid")

    # Configure settings fallbacks before importing them.
    os.environ["AAQTS_MT5_EXPECTED_LOGIN_FILE"] = str(LOGIN_FILE)
    os.environ["AAQTS_MT5_RISK_BASELINE_FILE"] = str(BASELINE_FILE)
    os.environ.setdefault("AAQTS_MT5_SERVER", expected_server)
    os.environ.setdefault("AAQTS_MARKET_DATA_PROVIDER", "MT5")
    os.environ.setdefault("AAQTS_NEWS_FILTER_ENABLED", "true")

    from config.settings import MT5_SYMBOL_MAP, MT5_TERMINAL_PATH

    terminal = Path(MT5_TERMINAL_PATH)
    if not terminal.is_file():
        fail(f"MT5 terminal not found: {terminal}")

    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        fail(f"MetaTrader5 package unavailable: {exc}")

    if not mt5.initialize(path=str(terminal)):
        fail(f"MT5 initialization failed: {mt5.last_error()}")
    try:
        account = mt5.account_info()
        terminal_info = mt5.terminal_info()
        if account is None or terminal_info is None:
            fail("MT5 terminal/account information unavailable")
        if int(getattr(account, "login", -1)) != int(expected_login):
            fail("connected login does not match pinned live account")
        if str(getattr(account, "server", "") or "").strip().lower() != expected_server.lower():
            fail("connected server does not match pinned live server")
        real_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2)
        if getattr(account, "trade_mode", None) != real_mode:
            fail("connected account is not REAL")

        quoted = 0
        candle_ready = 0
        for source, broker in MT5_SYMBOL_MAP.items():
            info = mt5.symbol_info(broker)
            if info is None:
                fail(f"broker symbol unavailable: {source} ({broker})")
            if not getattr(info, "visible", False) and not mt5.symbol_select(broker, True):
                fail(f"broker symbol cannot be selected: {source} ({broker})")
            tick = mt5.symbol_info_tick(broker)
            bid = float(getattr(tick, "bid", 0.0) or 0.0) if tick else 0.0
            ask = float(getattr(tick, "ask", 0.0) or 0.0) if tick else 0.0
            if bid > 0 and ask >= bid:
                quoted += 1
            for timeframe in (mt5.TIMEFRAME_M15, mt5.TIMEFRAME_H1):
                rates = mt5.copy_rates_from_pos(broker, timeframe, 1, 3)
                if rates is None or len(rates) < 2:
                    fail(f"completed broker candles unavailable for {source} ({broker})")
            candle_ready += 1

        baseline_text = BASELINE_FILE.read_text(encoding="utf-8").strip().replace("Z", "+00:00")
        try:
            baseline = datetime.fromisoformat(baseline_text)
            if baseline.tzinfo is None:
                raise ValueError
            baseline = baseline.astimezone(timezone.utc)
        except ValueError:
            fail("live risk baseline timestamp is invalid")
        if baseline > datetime.now(timezone.utc):
            fail("live risk baseline is in the future")

        print(
            "[live-preflight] REAL account identity OK | "
            f"balance={float(account.balance):.2f} equity={float(account.equity):.2f}"
        )
        print(
            f"[live-preflight] Broker data OK | symbols={len(MT5_SYMBOL_MAP)} "
            f"quoted={quoted} candle_ready={candle_ready}"
        )
        print(
            "[live-preflight] Algo Trading currently "
            + ("ON" if getattr(terminal_info, "trade_allowed", False) else "OFF")
        )
        print("[live-preflight] Preflight passed")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
