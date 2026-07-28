import json
import logging
import os
from datetime import datetime, timezone


class TradeLogger:
    def __init__(self, log_file="logs/trading.log"):
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        self.logger = logging.getLogger("forex_bot")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False

        if not self.logger.handlers:
            handler = logging.FileHandler(log_file)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)

    def log_event(self, event, level="INFO", **fields):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level.upper(),
            "event": event,
            **fields,
        }
        log_method = getattr(self.logger, level.lower(), self.logger.info)
        log_method(json.dumps(payload, default=str, sort_keys=True))

    def log_signal(self, symbol, signal, confidence):
        self.log_event(
            "signal_generated",
            symbol=symbol,
            signal=signal,
            confidence=confidence,
        )

    def log_trade(self, symbol, trade, position):
        self.log_event(
            "trade_plan_created",
            symbol=symbol,
            entry=trade["entry"],
            stop_loss=trade["stop_loss"],
            take_profit=trade["take_profit"],
            risk_reward=trade["risk_reward"],
            position=position,
        )

    def log_exception(self, event, exception, **fields):
        self.log_event(
            event,
            level="ERROR",
            error_type=type(exception).__name__,
            error=str(exception),
            **fields,
        )
