import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return bool(default)
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")

SYMBOLS = {
    "forex": [
        "EURUSD=X",
        "GBPUSD=X",
        "JPY=X",
        "AUDUSD=X",
        "CAD=X"
    ],

    "metals": [
        "GC=F",      # Gold
        "SI=F"       # Silver
    ],

    "crypto": [
        "BTC-USD",
        "ETH-USD",
        "SOL-USD"
    ]
}

# ==========================
# MULTI TIMEFRAME SETTINGS
# ==========================

HIGHER_TIMEFRAME = "1h"
TRADING_TIMEFRAME = "15m"
LOOKBACK_DAYS = "2020-01-01"
ACCOUNT_BALANCE = 1000
RISK_PERCENT = 1

# Strategy gates remain environment-configurable so research can tune them
# without editing production code.  The checked-in defaults preserve the most
# recent intraday policy.
MIN_ADX = float(os.getenv("AAQTS_MIN_ADX", "20"))
SIGNAL_SCORE_THRESHOLD = int(os.getenv("AAQTS_SIGNAL_SCORE_THRESHOLD", "55"))
MIN_SIGNAL_CONFIRMATIONS = int(os.getenv("AAQTS_MIN_SIGNAL_CONFIRMATIONS", "2"))
MIN_TRADE_QUALITY = int(os.getenv("AAQTS_MIN_TRADE_QUALITY", "55"))

# ==========================
# EXECUTION SETTINGS
# ==========================
# PAPER is the safe default. MT5_DEMO must be explicitly enabled in .env or
# the shell. MT5_LIVE is intentionally blocked until a separate live-release
# safety gate is implemented.
EXECUTION_MODE = os.getenv("AAQTS_EXECUTION_MODE", "PAPER").upper().strip()
MT5_TERMINAL_PATH = os.getenv(
    "AAQTS_MT5_TERMINAL_PATH",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
)
MT5_FIXED_LOT = float(os.getenv("AAQTS_MT5_FIXED_LOT", "0.01"))
MT5_MAX_OPEN_POSITIONS = int(os.getenv("AAQTS_MT5_MAX_OPEN_POSITIONS", "5"))
BOT_INTERVAL_SECONDS = int(os.getenv("AAQTS_BOT_INTERVAL_SECONDS", "300"))
NEWS_FILTER_ENABLED = _env_flag("AAQTS_NEWS_FILTER_ENABLED", False)
NEWS_CALENDAR_FILE = os.getenv("AAQTS_NEWS_CALENDAR_FILE", "").strip()

# Market-data provider symbol -> broker/MT5 symbol. Broker suffixes can be
# overridden later without touching strategy code.
MT5_SYMBOL_MAP = {
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "USDJPY=X": "USDJPY",
    "AUDUSD=X": "AUDUSD",
    "USDCAD=X": "USDCAD",
    "USDCHF=X": "USDCHF",
    "NZDUSD=X": "NZDUSD",
    "GC=F": "XAUUSD",
    "SI=F": "XAGUSD",
    "BTC-USD": "BTCUSD",
    "ETH-USD": "ETHUSD",
    "SOL-USD": "SOLUSD",
}
