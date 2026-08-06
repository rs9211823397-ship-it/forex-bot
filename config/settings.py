import math
import os
from pathlib import Path
from dotenv import load_dotenv

from config.symbol_policy import (
    filter_active_symbols,
    filter_executable_map,
    parse_disabled_broker_symbols,
)
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


def _positive_int(name, default):
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _positive_float(name, default):
    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")
    return value


def _bounded_float(name, default, lower, upper):
    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or value < lower or value > upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return value


def _bounded_int(name, default, lower, upper):
    value = int(os.getenv(name, str(default)))
    if value < lower or value > upper:
        raise ValueError(f"{name} must be between {lower} and {upper}")
    return value


def _default_mt5_terminal_path():
    """Return the first known local MT5 terminal without overriding env config."""
    program_files = Path(os.getenv("PROGRAMFILES", r"C:\Program Files"))
    appdata = os.getenv("APPDATA", "").strip()
    candidates = [program_files / "MetaTrader 5" / "terminal64.exe"]
    if appdata:
        candidates.extend(
            [
                Path(appdata) / "Exness JO MT5 Terminal" / "terminal64.exe",
                Path(appdata) / "Exness MT5 Terminal" / "terminal64.exe",
            ]
        )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return str(candidates[0])


# ==========================
# MULTI TIMEFRAME SETTINGS
# ==========================

HIGHER_TIMEFRAME = "1h"
TRADING_TIMEFRAME = "15m"
LOOKBACK_DAYS = "2020-01-01"
PAPER_STARTING_BALANCE = _positive_float("AAQTS_PAPER_STARTING_BALANCE", 1000.0)
ACCOUNT_BALANCE = PAPER_STARTING_BALANCE
RISK_PERCENT = _bounded_float("AAQTS_RISK_PERCENT", 1.0, 0.05, 5.0)

MIN_ADX = _bounded_float("AAQTS_MIN_ADX", 20.0, 0.0, 100.0)
SIGNAL_SCORE_THRESHOLD = _bounded_int("AAQTS_SIGNAL_SCORE_THRESHOLD", 55, -100, 100)
MIN_SIGNAL_CONFIRMATIONS = _bounded_int("AAQTS_MIN_SIGNAL_CONFIRMATIONS", 2, 1, 10)
MIN_TRADE_QUALITY = _bounded_int("AAQTS_MIN_TRADE_QUALITY", 55, 0, 100)

# ==========================
# EXECUTION SETTINGS
# ==========================

EXECUTION_MODE = os.getenv("AAQTS_EXECUTION_MODE", "PAPER").upper().strip()
if EXECUTION_MODE not in {"PAPER", "MT5_DEMO", "MT5_LIVE"}:
    raise ValueError("AAQTS_EXECUTION_MODE must be PAPER, MT5_DEMO, or MT5_LIVE")

# Small-account safety: temporarily remove high-minimum-risk metals from both
# scanning and execution. Set AAQTS_DISABLED_BROKER_SYMBOLS to an empty string
# later to re-enable the catalog defaults, or provide a different comma list.
DISABLED_BROKER_SYMBOLS = parse_disabled_broker_symbols(
    os.getenv("AAQTS_DISABLED_BROKER_SYMBOLS")
)
SYMBOLS = filter_active_symbols(
    active_symbols(include_paper_only=EXECUTION_MODE == "PAPER"),
    DISABLED_BROKER_SYMBOLS,
)

MT5_TERMINAL_PATH = os.getenv("AAQTS_MT5_TERMINAL_PATH", _default_mt5_terminal_path())
MT5_LOGIN = os.getenv("AAQTS_MT5_LOGIN", "").strip()
MT5_EXPECTED_LOGIN = os.getenv("AAQTS_MT5_EXPECTED_LOGIN", "").strip()
MT5_PASSWORD = os.getenv("AAQTS_MT5_PASSWORD", "").strip()
MT5_SERVER = os.getenv("AAQTS_MT5_SERVER", "").strip()
MT5_FIXED_LOT = _positive_float("AAQTS_MT5_FIXED_LOT", 0.01)
MT5_MAX_OPEN_POSITIONS = _bounded_int("AAQTS_MT5_MAX_OPEN_POSITIONS", 5, 1, 20)
BOT_INTERVAL_SECONDS = _bounded_int("AAQTS_BOT_INTERVAL_SECONDS", 300, 15, 86400)
MT5_MAX_TICK_AGE_SECONDS = _bounded_float("AAQTS_MT5_MAX_TICK_AGE_SECONDS", 15.0, 1.0, 300.0)
MT5_MAX_SPREAD_STOP_RATIO = _bounded_float(
    "AAQTS_MT5_MAX_SPREAD_STOP_RATIO", 0.25, 0.01, 1.0
)
PORTFOLIO_MAX_ABS_CORRELATION = _bounded_float(
    "AAQTS_PORTFOLIO_MAX_ABS_CORRELATION", 0.80, 0.0, 1.0
)
PORTFOLIO_MAX_CORRELATED_RISK_PERCENT = _bounded_float(
    "AAQTS_PORTFOLIO_MAX_CORRELATED_RISK_PERCENT", 2.0, 0.1, 100.0
)

# Production demo trading defaults to a fail-closed high-impact news filter.
NEWS_FILTER_ENABLED = _env_flag(
    "AAQTS_NEWS_FILTER_ENABLED",
    EXECUTION_MODE == "MT5_DEMO",
)
NEWS_CALENDAR_FILE = os.getenv("AAQTS_NEWS_CALENDAR_FILE", "").strip()
NEWS_CALENDAR_URL = os.getenv(
    "AAQTS_NEWS_CALENDAR_URL",
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
).strip()
NEWS_CALENDAR_CACHE = os.getenv(
    "AAQTS_NEWS_CALENDAR_CACHE",
    "runtime/news_calendar_cache.json",
).strip()
NEWS_REFRESH_MINUTES = _positive_int("AAQTS_NEWS_REFRESH_MINUTES", 30)
NEWS_MAX_STALE_MINUTES = _positive_int("AAQTS_NEWS_MAX_STALE_MINUTES", 360)
NEWS_PRE_EVENT_MINUTES = _positive_int("AAQTS_NEWS_PRE_EVENT_MINUTES", 30)
NEWS_POST_EVENT_MINUTES = _positive_int("AAQTS_NEWS_POST_EVENT_MINUTES", 20)
NEWS_BLOCKED_IMPACTS = tuple(
    impact.strip().upper()
    for impact in os.getenv("AAQTS_NEWS_BLOCKED_IMPACTS", "HIGH").split(",")
    if impact.strip()
)
if not NEWS_BLOCKED_IMPACTS or not set(NEWS_BLOCKED_IMPACTS).issubset(
    {"LOW", "MEDIUM", "HIGH"}
):
    raise ValueError(
        "AAQTS_NEWS_BLOCKED_IMPACTS must contain LOW, MEDIUM, and/or HIGH"
    )

SINGLE_ACCOUNT_MODE = _env_flag("AAQTS_SINGLE_ACCOUNT_MODE", True)
PRIMARY_ACCOUNT_ID = os.getenv("AAQTS_PRIMARY_ACCOUNT_ID", "").strip().lower()

# Market-data provider symbol -> broker/MT5 symbol for approved new entries.
MT5_SYMBOL_SUFFIX = os.getenv("AAQTS_MT5_SYMBOL_SUFFIX", "").strip()
_BASE_MT5_SYMBOL_MAP = filter_executable_map(
    executable_symbol_map(),
    DISABLED_BROKER_SYMBOLS,
)
MT5_SYMBOL_MAP = {
    source: f"{broker}{MT5_SYMBOL_SUFFIX}"
    for source, broker in _BASE_MT5_SYMBOL_MAP.items()
}
