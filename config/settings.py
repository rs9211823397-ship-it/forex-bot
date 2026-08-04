import math
import os
from pathlib import Path
from dotenv import load_dotenv

from config.symbols import active_symbols, executable_symbol_map

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

# ==========================
# MULTI TIMEFRAME SETTINGS
# ==========================

HIGHER_TIMEFRAME = "1h"
TRADING_TIMEFRAME = "15m"
LOOKBACK_DAYS = "2020-01-01"
PAPER_STARTING_BALANCE = float(
    os.getenv("AAQTS_PAPER_STARTING_BALANCE", "1000")
)
if not math.isfinite(PAPER_STARTING_BALANCE) or PAPER_STARTING_BALANCE <= 0:
    raise ValueError("AAQTS_PAPER_STARTING_BALANCE must be greater than zero")
# Backward-compatible research/reporting alias.
ACCOUNT_BALANCE = PAPER_STARTING_BALANCE
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
SYMBOLS = active_symbols(include_paper_only=EXECUTION_MODE == "PAPER")
MT5_TERMINAL_PATH = os.getenv(
    "AAQTS_MT5_TERMINAL_PATH",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
)
MT5_LOGIN = os.getenv("AAQTS_MT5_LOGIN", "").strip()
MT5_EXPECTED_LOGIN = os.getenv("AAQTS_MT5_EXPECTED_LOGIN", "").strip()
MT5_PASSWORD = os.getenv("AAQTS_MT5_PASSWORD", "").strip()
MT5_SERVER = os.getenv("AAQTS_MT5_SERVER", "").strip()
MT5_FIXED_LOT = float(os.getenv("AAQTS_MT5_FIXED_LOT", "0.01"))
MT5_MAX_OPEN_POSITIONS = int(os.getenv("AAQTS_MT5_MAX_OPEN_POSITIONS", "5"))
BOT_INTERVAL_SECONDS = int(os.getenv("AAQTS_BOT_INTERVAL_SECONDS", "300"))
NEWS_FILTER_ENABLED = _env_flag("AAQTS_NEWS_FILTER_ENABLED", False)
NEWS_CALENDAR_FILE = os.getenv("AAQTS_NEWS_CALENDAR_FILE", "").strip()

# The user-facing default is one personally managed account.  The underlying
# registry and supervisor retain multi-account support for a future opt-in
# deployment, but a missing flag must never expose parent-account controls.
SINGLE_ACCOUNT_MODE = _env_flag("AAQTS_SINGLE_ACCOUNT_MODE", True)
PRIMARY_ACCOUNT_ID = os.getenv("AAQTS_PRIMARY_ACCOUNT_ID", "").strip().lower()

# Market-data provider symbol -> broker/MT5 symbol for approved new entries.
MT5_SYMBOL_MAP = executable_symbol_map()
