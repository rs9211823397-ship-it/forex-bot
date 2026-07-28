import os

from broker.mt5_broker import MT5Broker
from broker.paper_broker import PaperBroker


def create_broker(mode=None, **kwargs):
    """Create a broker adapter with paper trading as the fail-safe default.

    Live MT5 execution must be selected explicitly with mode="mt5" or
    FOREX_BOT_BROKER=mt5. Credentials are read only when live mode is chosen.
    """
    selected = (mode or os.getenv("FOREX_BOT_BROKER", "paper")).strip().lower()
    if selected == "paper":
        return PaperBroker(**kwargs)
    if selected != "mt5":
        raise ValueError("Broker mode must be 'paper' or 'mt5'")

    settings = {
        "login": os.getenv("MT5_LOGIN"),
        "password": os.getenv("MT5_PASSWORD"),
        "server": os.getenv("MT5_SERVER"),
        "terminal_path": os.getenv("MT5_TERMINAL_PATH"),
        "deviation": int(os.getenv("MT5_DEVIATION", "20")),
        "magic": int(os.getenv("MT5_MAGIC", "31003")),
    }
    settings.update(kwargs)
    missing = [name for name in ("login", "password", "server") if not settings.get(name)]
    if missing:
        raise ValueError(f"Missing required MT5 settings: {', '.join(missing)}")
    return MT5Broker(**settings)
