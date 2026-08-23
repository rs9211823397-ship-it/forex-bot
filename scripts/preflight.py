#!/usr/bin/env python3
"""Release preflight checks for the forex-bot repository."""

import importlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_PACKAGES = {
    "numpy": "numpy",
    "pandas": "pandas",
    "yfinance": "yfinance",
    "dotenv": "python-dotenv",
}

OPTIONAL_PACKAGES = {
    "telegram": "python-telegram-bot",
    "MetaTrader5": "MetaTrader5 (Windows only)",
}


def fail(message: str) -> None:
    print(f"[preflight] ERROR: {message}")
    raise SystemExit(1)


def check_python_version() -> None:
    if sys.version_info < (3, 10):
        fail("Python 3.10+ is required")
    print(f"[preflight] Python {sys.version.split()[0]} OK")


def check_repo_root() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    if not (repo_root / "requirements.txt").exists():
        fail("Repository root could not be determined")
    os.chdir(repo_root)
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    print(f"[preflight] Repository root: {repo_root}")
    return repo_root


def check_required_packages() -> None:
    missing = []
    for module_name, package_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append(package_name)
    if missing:
        fail("Missing required packages: " + ", ".join(sorted(missing)))
    print("[preflight] Required packages OK")


def check_optional_packages() -> None:
    missing = []
    for module_name, package_name in OPTIONAL_PACKAGES.items():
        try:
            importlib.import_module(module_name)
        except Exception:
            missing.append(package_name)
    if missing:
        print(f"[preflight] Optional packages not installed: {', '.join(sorted(missing))}")
    else:
        print("[preflight] Optional packages OK")


def check_output_folders(repo_root: Path) -> None:
    required_dirs = [repo_root / "logs", repo_root / "outputs", repo_root / "runtime"]
    for directory in required_dirs:
        directory.mkdir(exist_ok=True)
        if not directory.is_dir() or not os.access(directory, os.W_OK):
            fail(f"Output folder is not writable: {directory}")
    print("[preflight] Output folders OK")


def check_execution_mode() -> None:
    from config.settings import EXECUTION_MODE, STRATEGY_MODE, UTBOT_EXIT_MODE
    if EXECUTION_MODE not in {"PAPER", "MT5_DEMO", "MT5_LIVE"}:
        fail(f"Unsupported AAQTS_EXECUTION_MODE: {EXECUTION_MODE}")
    if EXECUTION_MODE == "MT5_LIVE":
        if os.getenv("AAQTS_LIVE_TRADING_ACK", "").strip() != "I_UNDERSTAND_REAL_MONEY":
            fail("MT5_LIVE requires the explicit real-money acknowledgement")
        if STRATEGY_MODE != "UT_BOT" or UTBOT_EXIT_MODE != "ATR_TRAIL":
            fail("MT5_LIVE requires protected UT_BOT ATR_TRAIL mode")
    print(f"[preflight] Execution mode {EXECUTION_MODE} OK")
    print(f"[preflight] Strategy mode {STRATEGY_MODE} OK")


def check_market_data_policy() -> None:
    from config.settings import EXECUTION_MODE
    from data.market_data import MarketData

    try:
        market = MarketData(cache_downloads=False)
    except Exception as exc:
        fail(f"Market-data policy invalid: {exc}")
    if EXECUTION_MODE in {"MT5_DEMO", "MT5_LIVE"} and market.provider != "MT5":
        fail(f"{EXECUTION_MODE} requires broker-native MT5 market data")
    print(
        f"[preflight] Market data policy OK (provider={market.provider}, "
        f"cached_fallback={market.allow_cache_fallback})"
    )


def check_news_calendar() -> None:
    from config.settings import (
        EXECUTION_MODE,
        NEWS_CALENDAR_CACHE,
        NEWS_CALENDAR_FILE,
        NEWS_CALENDAR_URL,
        NEWS_FILTER_ENABLED,
        NEWS_MAX_STALE_MINUTES,
        NEWS_REFRESH_MINUTES,
        STRATEGY_MODE,
        UTBOT_EXIT_MODE,
    )
    from risk.news_calendar import build_news_provider

    pure_signal_demo = (
        EXECUTION_MODE == "MT5_DEMO"
        and STRATEGY_MODE == "UT_BOT"
        and UTBOT_EXIT_MODE == "OPPOSITE_SIGNAL"
    )
    if EXECUTION_MODE in {"MT5_DEMO", "MT5_LIVE"} and not NEWS_FILTER_ENABLED and not pure_signal_demo:
        fail(f"{EXECUTION_MODE} requires the fail-closed news filter")
    if not NEWS_FILTER_ENABLED:
        print("[preflight] News filter disabled (signal-lifecycle/PAPER mode)")
        return
    try:
        provider = build_news_provider(
            enabled=True,
            calendar_file=NEWS_CALENDAR_FILE,
            calendar_url=NEWS_CALENDAR_URL,
            cache_path=NEWS_CALENDAR_CACHE,
            refresh_minutes=NEWS_REFRESH_MINUTES,
            max_stale_minutes=NEWS_MAX_STALE_MINUTES,
        )
        assert provider is not None
        events = provider.events
        now = datetime.now(timezone.utc)
        future = sum(event.event_time >= now for event in events)
        source = NEWS_CALENDAR_FILE or NEWS_CALENDAR_URL
        print(
            f"[preflight] News calendar OK ({len(events)} events, "
            f"future={future}, source={source})"
        )
    except Exception as exc:
        fail(f"News calendar unavailable or stale: {exc}")


def check_symbol_catalog() -> None:
    from config.instruments import get_instrument_spec
    from config.settings import EXECUTION_MODE, MT5_SYMBOL_MAP, SYMBOLS

    active = [symbol for group in SYMBOLS.values() for symbol in group]
    for symbol in active:
        get_instrument_spec(symbol)
    if EXECUTION_MODE in {"MT5_DEMO", "MT5_LIVE"}:
        missing = sorted(set(active).difference(MT5_SYMBOL_MAP))
        if missing:
            fail(
                "Active MT5 symbols are missing executable mappings: "
                + ", ".join(missing)
            )
    print(f"[preflight] Symbol catalog OK ({len(active)} active)")


def check_mt5_broker() -> None:
    """Validate the pinned MT5 venue and candle access without placing orders."""
    from config.settings import (
        EXECUTION_MODE,
        MT5_EXPECTED_LOGIN,
        MT5_LOGIN,
        MT5_PASSWORD,
        MT5_SERVER,
        MT5_SYMBOL_MAP,
        MT5_TERMINAL_PATH,
        MT5_USE_PREAUTHENTICATED_SESSION,
        STRATEGY_MODE,
        UTBOT_EXIT_MODE,
    )

    if EXECUTION_MODE not in {"MT5_DEMO", "MT5_LIVE"}:
        return
    terminal_path = Path(MT5_TERMINAL_PATH)
    if not terminal_path.is_file():
        fail(f"MT5 terminal was not found: {terminal_path}")
    if not MT5_EXPECTED_LOGIN:
        fail(
            f"{EXECUTION_MODE} requires a pinned expected login; run "
            "scripts/pin_mt5_account.py or save-demo-credentials.ps1"
        )
    if EXECUTION_MODE == "MT5_LIVE" and MT5_USE_PREAUTHENTICATED_SESSION:
        fail("MT5_LIVE forbids a preauthenticated session")
    if not MT5_USE_PREAUTHENTICATED_SESSION and not (
        MT5_LOGIN and MT5_PASSWORD and MT5_SERVER
    ):
        fail(
            f"{EXECUTION_MODE} requires complete LOGIN/PASSWORD/SERVER credentials"
            + (
                " or AAQTS_MT5_USE_PREAUTHENTICATED_SESSION=true"
                if EXECUTION_MODE == "MT5_DEMO"
                else ""
            )
        )

    try:
        from execution.live_mt5_executor import LiveMT5Executor
        from execution.mt5_executor import ExecutionConfig, MT5Executor

        executor_class = LiveMT5Executor if EXECUTION_MODE == "MT5_LIVE" else MT5Executor
        executor = executor_class(
            ExecutionConfig(
                terminal_path=str(terminal_path),
                login=int(MT5_LOGIN) if MT5_LOGIN else None,
                expected_login=(int(MT5_EXPECTED_LOGIN) if MT5_EXPECTED_LOGIN else None),
                password=MT5_PASSWORD,
                server=MT5_SERVER,
            )
        )
        executor.connect()
        try:
            account = executor.account_snapshot()
            unquoted = []
            quoted = 0
            candle_ready = 0
            mt5 = executor.mt5
            for source_symbol, broker_symbol in MT5_SYMBOL_MAP.items():
                info = executor.symbol_info(broker_symbol)
                tick = executor.symbol_tick(broker_symbol)
                minimum = float(getattr(info, "volume_min", 0.0) or 0.0)
                maximum = float(getattr(info, "volume_max", 0.0) or 0.0)
                step = float(getattr(info, "volume_step", 0.0) or 0.0)
                bid = float(getattr(tick, "bid", 0.0) or 0.0)
                ask = float(getattr(tick, "ask", 0.0) or 0.0)
                if minimum <= 0 or maximum < minimum or step <= 0:
                    fail(
                        f"Invalid broker volume metadata for {source_symbol} "
                        f"({broker_symbol})"
                    )
                if bid <= 0 or ask <= 0 or ask < bid:
                    unquoted.append(f"{source_symbol} ({broker_symbol})")
                else:
                    quoted += 1

                timeframes = ["TIMEFRAME_M15"]
                if STRATEGY_MODE != "UT_BOT":
                    timeframes.append("TIMEFRAME_H1")
                for timeframe_name in timeframes:
                    timeframe = getattr(mt5, timeframe_name, None)
                    if timeframe is None:
                        fail(f"MT5 API lacks {timeframe_name}")
                    rates = mt5.copy_rates_from_pos(broker_symbol, timeframe, 1, 3)
                    if rates is None or len(rates) < 2:
                        fail(
                            f"Broker candle access failed for {source_symbol} "
                            f"({broker_symbol}) {timeframe_name}: {mt5.last_error()}"
                        )
                candle_ready += 1

            if quoted == 0:
                fail("No mapped MT5 symbols currently have an executable quote")
            if unquoted:
                print(
                    "[preflight] WARNING: mapped symbol(s) currently have no "
                    "executable quote (likely closed broker session): "
                    + ", ".join(unquoted)
                )
            print(
                f"[preflight] {EXECUTION_MODE} broker OK "
                f"(balance={account.balance:.2f}, equity={account.equity:.2f}, "
                f"symbols={len(MT5_SYMBOL_MAP)}, quoted={quoted}, "
                f"candle_ready={candle_ready}, "
                f"authentication={'terminal-session' if MT5_USE_PREAUTHENTICATED_SESSION else 'explicit'})"
            )
        finally:
            executor.shutdown()
    except SystemExit:
        raise
    except Exception as exc:
        fail(f"{EXECUTION_MODE} broker preflight failed: {exc}")


def main() -> None:
    check_python_version()
    repo_root = check_repo_root()
    check_required_packages()
    check_optional_packages()
    check_output_folders(repo_root)
    check_execution_mode()
    check_market_data_policy()
    check_symbol_catalog()
    check_news_calendar()
    check_mt5_broker()
    print("[preflight] Preflight passed")


if __name__ == "__main__":
    main()
