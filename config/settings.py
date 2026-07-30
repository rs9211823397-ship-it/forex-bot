import os

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

HIGHER_TIMEFRAME = "1d"
TRADING_TIMEFRAME = "1h"
LOOKBACK_DAYS = "2020-01-01"
ACCOUNT_BALANCE = 1000
RISK_PERCENT = 1

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
MT5_MAX_OPEN_POSITIONS = int(os.getenv("AAQTS_MT5_MAX_OPEN_POSITIONS", "3"))

# Market-data provider symbol -> broker/MT5 symbol. Broker suffixes can be
# overridden later without touching strategy code.
MT5_SYMBOL_MAP = {
    "EURUSD=X": "EURUSD",
    "GBPUSD=X": "GBPUSD",
    "JPY=X": "USDJPY",
    "AUDUSD=X": "AUDUSD",
    "CAD=X": "USDCAD",
    "GC=F": "XAUUSD",
    "SI=F": "XAGUSD",
    "BTC-USD": "BTCUSD",
    "ETH-USD": "ETHUSD",
}
