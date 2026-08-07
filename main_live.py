"""Guarded real-money AAQTS entry point.

Strategy, sizing, portfolio risk, cooldown, position management and Telegram
integration remain the same as the normal application. This entry point only
adds live-account identity, market-data and release safeguards.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
LIVE_LOGIN_FILE = REPO_ROOT / "runtime" / "mt5_live_expected_login.txt"
LIVE_SERVER_FILE = REPO_ROOT / "runtime" / "mt5_live_expected_server.txt"
LIVE_BASELINE_FILE = REPO_ROOT / "runtime" / "mt5_live_risk_baseline_utc.txt"
LIVE_ACK_VALUE = "I_UNDERSTAND_REAL_MONEY"

# These defaults are applied before config.settings is imported.
os.environ.setdefault("AAQTS_MT5_EXPECTED_LOGIN_FILE", str(LIVE_LOGIN_FILE))
os.environ.setdefault("AAQTS_MT5_RISK_BASELINE_FILE", str(LIVE_BASELINE_FILE))
os.environ.setdefault("AAQTS_MARKET_DATA_PROVIDER", "MT5")
os.environ.setdefault("AAQTS_NEWS_FILTER_ENABLED", "true")
if not os.getenv("AAQTS_MT5_SERVER", "").strip() and LIVE_SERVER_FILE.is_file():
    os.environ["AAQTS_MT5_SERVER"] = LIVE_SERVER_FILE.read_text(encoding="utf-8").strip()

from config.settings import EXECUTION_MODE  # noqa: E402
from data.market_data import MarketData  # noqa: E402
from main import (  # noqa: E402
    HEARTBEAT_INTERVAL_SECONDS,
    TradingApplication,
    engine_instance_lock,
    write_runtime_state,
)


logger = logging.getLogger(__name__)


class LiveMarketData(MarketData):
    """Broker-native market data that never falls back to cache and stays fresh."""

    def __init__(self) -> None:
        super().__init__(
            execution_mode="MT5_LIVE",
            provider="MT5",
            allow_cache_fallback=False,
            max_stale_bars=1.5,
        )

    def download_data(self, symbol, interval=None, *, as_of=None, use_cache=True):
        frame = super().download_data(
            symbol,
            interval,
            as_of=as_of,
            use_cache=False,
        )
        self._assert_fresh(frame, symbol, interval or "1d")
        frame.attrs["source"] = "MT5"
        frame.attrs["fresh"] = True
        return frame


class LiveTradingApplication(TradingApplication):
    """TradingApplication with live-specific fail-closed data/risk routing."""

    def __init__(self) -> None:
        if EXECUTION_MODE != "MT5_LIVE":
            raise RuntimeError("main_live.py requires AAQTS_EXECUTION_MODE=MT5_LIVE")
        if os.getenv("AAQTS_LIVE_TRADING_ACK", "").strip() != LIVE_ACK_VALUE:
            raise RuntimeError(
                "Live release acknowledgement missing; real-money execution remains locked"
            )
        if not LIVE_LOGIN_FILE.is_file() or not LIVE_SERVER_FILE.is_file():
            raise RuntimeError("Live MT5 identity is not pinned locally")
        if not LIVE_BASELINE_FILE.is_file():
            raise RuntimeError("Live risk baseline is not initialized")
        super().__init__()
        self.market = LiveMarketData()

    def _risk_context(self, decision_time):
        return self._mt5_risk_context(decision_time)

    def _process_symbol(self, symbol, data, higher_tf):
        if not self._frame_is_demo_safe(data):
            raise RuntimeError(f"Unsafe/stale live lower-timeframe data blocked for {symbol}")
        if not self._frame_is_demo_safe(higher_tf):
            raise RuntimeError(f"Unsafe/stale live higher-timeframe data blocked for {symbol}")
        return super()._process_symbol(symbol, data, higher_tf)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    app = LiveTradingApplication()
    with engine_instance_lock(app.account_id):
        try:
            app.controller.start_bot()
            logger.warning("AAQTS MT5_LIVE ENGINE STARTED: REAL MONEY ORDERS ARE ENABLED")
            next_heartbeat = 0.0
            while app.controller.status() != "STOPPED":
                app._process_control_commands()
                now = time.monotonic()
                if now >= next_heartbeat:
                    write_runtime_state(
                        account_id=app.account_id,
                        status=app.controller.status(),
                        execution_mode="MT5_LIVE",
                        live_trading=True,
                    )
                    next_heartbeat = now + HEARTBEAT_INTERVAL_SECONDS
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("AAQTS live shutdown requested")
        finally:
            app.controller.stop_bot()
            write_runtime_state(
                account_id=app.account_id,
                status="STOPPED",
                phase="STOPPED",
                execution_mode="MT5_LIVE",
                live_trading=True,
                stopped_at=datetime.now(timezone.utc).isoformat(),
            )


if __name__ == "__main__":
    main()
