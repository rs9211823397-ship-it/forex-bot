from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class BacktestCosts:
    spread: float = 0.0
    slippage: float = 0.0
    commission_per_unit: float = 0.0


class BacktestEngine:
    """Single-position event-driven backtester with realistic transaction costs."""

    def __init__(
        self,
        data,
        strategy: Callable[[int], str],
        initial_balance: float = 10_000.0,
        position_size: float = 1.0,
        costs: Optional[BacktestCosts] = None,
    ):
        if initial_balance <= 0:
            raise ValueError("initial_balance must be positive")
        if position_size <= 0:
            raise ValueError("position_size must be positive")

        self.data = data
        self.strategy = strategy
        self.initial_balance = float(initial_balance)
        self.position_size = float(position_size)
        self.costs = costs or BacktestCosts()
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []

    def _entry_fill(self, side: str, price: float) -> float:
        half_spread = self.costs.spread / 2
        friction = half_spread + self.costs.slippage
        return price + friction if side == "LONG" else price - friction

    def _exit_fill(self, side: str, price: float) -> float:
        half_spread = self.costs.spread / 2
        friction = half_spread + self.costs.slippage
        return price - friction if side == "LONG" else price + friction

    def _commission(self) -> float:
        return self.costs.commission_per_unit * self.position_size

    @staticmethod
    def _multipliers(adx: float):
        if adx >= 40:
            return 2.5, 4.5
        if adx >= 30:
            return 2.0, 4.0
        return 1.5, 3.0

    def run(self):
        self.trades = []
        self.equity_curve = []

        position = None
        balance = self.initial_balance

        for i, (timestamp, row) in enumerate(self.data.iterrows()):
            close = float(row["close"])
            high = float(row.get("high", close))
            low = float(row.get("low", close))
            atr = float(row["ATR"])
            adx = float(row["ADX"])
            signal = str(self.strategy(i)).upper()
            sl_mult, tp_mult = self._multipliers(adx)

            if position is None and signal in {"BUY", "SELL"}:
                side = "LONG" if signal == "BUY" else "SHORT"
                entry = self._entry_fill(side, close)
                stop = entry - sl_mult * atr if side == "LONG" else entry + sl_mult * atr
                target = entry + tp_mult * atr if side == "LONG" else entry - tp_mult * atr
                entry_commission = self._commission()
                balance -= entry_commission
                position = {
                    "side": side,
                    "entry_price": entry,
                    "entry_time": timestamp,
                    "stop_loss": stop,
                    "take_profit": target,
                    "entry_commission": entry_commission,
                }

            exit_reason = None
            exit_reference = None
            if position:
                if position["side"] == "LONG":
                    if low <= position["stop_loss"]:
                        exit_reason, exit_reference = "STOP_LOSS", position["stop_loss"]
                    elif high >= position["take_profit"]:
                        exit_reason, exit_reference = "TAKE_PROFIT", position["take_profit"]
                    elif signal == "SELL":
                        exit_reason, exit_reference = "OPPOSITE_SIGNAL", close
                else:
                    if high >= position["stop_loss"]:
                        exit_reason, exit_reference = "STOP_LOSS", position["stop_loss"]
                    elif low <= position["take_profit"]:
                        exit_reason, exit_reference = "TAKE_PROFIT", position["take_profit"]
                    elif signal == "BUY":
                        exit_reason, exit_reference = "OPPOSITE_SIGNAL", close

            if position and exit_reason:
                exit_price = self._exit_fill(position["side"], float(exit_reference))
                direction = 1 if position["side"] == "LONG" else -1
                gross_pnl = (
                    (exit_price - position["entry_price"])
                    * direction
                    * self.position_size
                )
                exit_commission = self._commission()
                net_pnl = gross_pnl - exit_commission
                balance += net_pnl

                self.trades.append({
                    "side": position["side"],
                    "entry_time": position["entry_time"],
                    "exit_time": timestamp,
                    "entry_price": position["entry_price"],
                    "exit_price": exit_price,
                    "stop_loss": position["stop_loss"],
                    "take_profit": position["take_profit"],
                    "position_size": self.position_size,
                    "gross_pnl": gross_pnl,
                    "commission": position["entry_commission"] + exit_commission,
                    "net_pnl": net_pnl - position["entry_commission"],
                    "exit_reason": exit_reason,
                    "balance": balance,
                })
                position = None

            floating = 0.0
            if position:
                direction = 1 if position["side"] == "LONG" else -1
                floating = (
                    close - position["entry_price"]
                ) * direction * self.position_size

            self.equity_curve.append({
                "time": timestamp,
                "balance": balance,
                "equity": balance + floating,
            })

        return self.trades
