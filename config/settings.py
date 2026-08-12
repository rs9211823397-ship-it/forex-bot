import math
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

from config.symbol_policy import (
    filter_active_symbols,
    filter_executable_map,
    parse_disabled_broker_symbols,
)
from config.symbols import active_symbols, executable_symbol_map

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / '.env')


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


def _optional_positive_int(name, default=0):
    """Return None when a zero value explicitly disables a count-based limit."""
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} must be zero (disabled) or greater than zero")
    return None if value == 0 else value


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


def _pinned_login_file() -> Path:
    configured = os.getenv("AAQTS_MT5_EXPECTED_LOGIN_FILE", "runtime/mt5_expected_login.txt").strip()
    path = Path(configured)
    return path if path.is_absolute() else REPO_ROOT / path


def _read_pinned_login() -> str:
    try:
        value = _pinned_login_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if value and not value.isdigit():
        raise ValueError("Pinned MT5 login file must contain only the numeric account login")
    return value


def _risk_baseline_file() -> Path:
    configured = os.getenv(
        "AAQTS_MT5_RISK_BASELINE_FILE",
        "runtime/mt5_risk_baseline_utc.txt",
    ).strip()
    path = Path(configured)
    return path if path.is_absolute() else REPO_ROOT / path


def _read_risk_baseline() -> datetime | None:
    explicit = os.getenv("AAQTS_MT5_RISK_BASELINE_UTC", "").strip()
    if explicit:
        value = explicit
    else:
        try:
            value = _risk_baseline_file().read_text(encoding="utf-8").strip()
        except OSError:
            return None
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            "MT5 risk baseline must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("MT5 risk baseline must include a timezone")
    return parsed.astimezone(timezone.utc)


# ==========================
# MULTI TIMEFRAME SETTINGS
# ==========================

HIGHER_TIMEFRAME = "1h"
TRADING_TIMEFRAME = "15m"
LOOKBACK_DAYS = "2020-01-01"
PAPER_STARTING_BALANCE = _positive_float("AAQTS_PAPER_STARTING_BALANCE", 1000.0)
ACCOUNT_BALANCE = PAPER_STARTING_BALANCE
RISK_PERCENT = _bounded_float("AAQTS_RISK_PERCENT", 3.0, 0.05, 5.0)

MIN_ADX = _bounded_float("AAQTS_MIN_ADX", 20.0, 0.0, 100.0)
# One canonical ADX eligibility boundary is shared by signal validation and
# every regime classifier.  Regime logic may still combine ADX with EMA slope,
# separation and volatility, but it must not silently introduce a second
# stronger ADX gate after the signal validator has accepted the candle.
REGIME_ADX_TREND_THRESHOLD = MIN_ADX
REGIME_ADX_RANGE_THRESHOLD = MIN_ADX
MIN_REGIME_CONFIDENCE = _bounded_float(
    "AAQTS_MIN_REGIME_CONFIDENCE", 35.0, 0.0, 100.0
)
SIGNAL_SCORE_THRESHOLD = _bounded_int("AAQTS_SIGNAL_SCORE_THRESHOLD", 55, -100, 100)
MIN_SIGNAL_CONFIRMATIONS = _bounded_int("AAQTS_MIN_SIGNAL_CONFIRMATIONS", 2, 1, 10)
MIN_TRADE_QUALITY = _bounded_int("AAQTS_MIN_TRADE_QUALITY", 55, 0, 100)

# RSI is an opposing-extreme veto, not a positive confirmation. It may block
# only when the matching Bollinger extreme and an opposing reversal candle
# independently confirm exhaustion.
RSI_BAND_VETO_OVERBOUGHT = _bounded_float(
    "AAQTS_RSI_BAND_VETO_OVERBOUGHT", 78.0, 50.0, 100.0
)
RSI_BAND_VETO_OVERSOLD = _bounded_float(
    "AAQTS_RSI_BAND_VETO_OVERSOLD", 22.0, 0.0, 50.0
)

# Count-based trade-frequency limits are disabled by default (0 = disabled).
# Hard portfolio protections remain active: daily/weekly loss, equity drawdown,
# maximum open positions, portfolio heat, correlation, spread and news gates.
MAX_DAILY_LOSS_PERCENT = _bounded_float("AAQTS_MAX_DAILY_LOSS_PERCENT", 6.0, 0.1, 100.0)
MAX_WEEKLY_LOSS_PERCENT = _bounded_float("AAQTS_MAX_WEEKLY_LOSS_PERCENT", 12.0, 0.1, 100.0)
MAX_EQUITY_DRAWDOWN_PERCENT = _bounded_float("AAQTS_MAX_EQUITY_DRAWDOWN_PERCENT", 15.0, 0.1, 100.0)
MAX_CONSECUTIVE_LOSSES = _optional_positive_int("AAQTS_MAX_CONSECUTIVE_LOSSES", 0)
MAX_DAILY_TRADES = _optional_positive_int("AAQTS_MAX_DAILY_TRADES", 0)
MAX_PORTFOLIO_RISK_PERCENT = _bounded_float("AAQTS_MAX_PORTFOLIO_RISK_PERCENT", 6.0, 0.1, 100.0)

# ==========================
# EXECUTION SETTINGS
# ==========================

EXECUTION_MODE = os.getenv("AAQTS_EXECUTION_MODE", "PAPER").upper().strip()
if EXECUTION_MODE not in {"PAPER", "MT5_DEMO", "MT5_LIVE"}:
    raise ValueError("AAQTS_EXECUTION_MODE must be PAPER, MT5_DEMO, or MT5_LIVE")

DISABLED_BROKER_SYMBOLS = parse_disabled_broker_symbols(
    os.getenv("AAQTS_DISABLED_BROKER_SYMBOLS")
)
SYMBOLS = filter_active_symbols(
    active_symbols(include_paper_only=EXECUTION_MODE == "PAPER"),
    DISABLED_BROKER_SYMBOLS,
)

MT5_TERMINAL_PATH = os.getenv("AAQTS_MT5_TERMINAL_PATH", _default_mt5_terminal_path())
MT5_USE_PREAUTHENTICATED_SESSION = _env_flag(
    "AAQTS_MT5_USE_PREAUTHENTICATED_SESSION",
    False,
)
if MT5_USE_PREAUTHENTICATED_SESSION and EXECUTION_MODE == "MT5_LIVE":
    raise ValueError(
        "AAQTS_MT5_USE_PREAUTHENTICATED_SESSION is not allowed in MT5_LIVE; "
        "live execution requires explicit pinned credentials"
    )

_MT5_CONFIGURED_LOGIN = os.getenv("AAQTS_MT5_LOGIN", "").strip()
_MT5_CONFIGURED_PASSWORD = os.getenv("AAQTS_MT5_PASSWORD", "").strip()
_MT5_CONFIGURED_SERVER = os.getenv("AAQTS_MT5_SERVER", "").strip()

# A deliberate preauthenticated-session selection must override stale values
# left in .env.  Blank PowerShell environment variables alone are not a
# reliable way to express this because dotenv/configuration precedence differs
# across launch methods.
MT5_LOGIN = "" if MT5_USE_PREAUTHENTICATED_SESSION else _MT5_CONFIGURED_LOGIN
MT5_EXPECTED_LOGIN = os.getenv("AAQTS_MT5_EXPECTED_LOGIN", "").strip() or _read_pinned_login()
MT5_EXPECTED_LOGIN_FILE = str(_pinned_login_file())
MT5_RISK_BASELINE_UTC = _read_risk_baseline()
MT5_RISK_BASELINE_FILE = str(_risk_baseline_file())
MT5_PASSWORD = "" if MT5_USE_PREAUTHENTICATED_SESSION else _MT5_CONFIGURED_PASSWORD
MT5_SERVER = "" if MT5_USE_PREAUTHENTICATED_SESSION else _MT5_CONFIGURED_SERVER
MT5_FIXED_LOT = _positive_float("AAQTS_MT5_FIXED_LOT", 0.05)
MT5_MAX_OPEN_POSITIONS = _bounded_int("AAQTS_MT5_MAX_OPEN_POSITIONS", 3, 1, 20)
BOT_INTERVAL_SECONDS = _bounded_int("AAQTS_BOT_INTERVAL_SECONDS", 300, 15, 86400)
POSITION_MANAGEMENT_INTERVAL_SECONDS = _bounded_int(
    "AAQTS_POSITION_MANAGEMENT_INTERVAL_SECONDS", 10, 1, 60
)
MT5_MAX_TICK_AGE_SECONDS = _bounded_float("AAQTS_MT5_MAX_TICK_AGE_SECONDS", 15.0, 1.0, 300.0)
MT5_MAX_SPREAD_STOP_RATIO = _bounded_float(
    "AAQTS_MT5_MAX_SPREAD_STOP_RATIO", 0.35, 0.01, 1.0
)
PORTFOLIO_MAX_ABS_CORRELATION = _bounded_float(
    "AAQTS_PORTFOLIO_MAX_ABS_CORRELATION", 0.80, 0.0, 1.0
)
PORTFOLIO_MAX_CORRELATED_RISK_PERCENT = _bounded_float(
    "AAQTS_PORTFOLIO_MAX_CORRELATED_RISK_PERCENT", 4.5, 0.1, 100.0
)

# Production demo trading defaults to a fail-closed high-impact news filter.
NEWS_FILTER_ENABLED = _env_flag(
    "AAQTS_NEWS_FILTER_ENABLED",
    EXECUTION_MODE in {"MT5_DEMO", "MT5_LIVE"},
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

MT5_SYMBOL_SUFFIX = os.getenv("AAQTS_MT5_SYMBOL_SUFFIX", "").strip()
_BASE_MT5_SYMBOL_MAP = filter_executable_map(
    executable_symbol_map(),
    DISABLED_BROKER_SYMBOLS,
)
MT5_SYMBOL_MAP = {
    source: f"{broker}{MT5_SYMBOL_SUFFIX}"
    for source, broker in _BASE_MT5_SYMBOL_MAP.items()
}
