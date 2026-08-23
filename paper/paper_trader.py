import csv
import os
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from config.settings import PAPER_STARTING_BALANCE
from config.instruments import get_instrument_spec


class PaperTrader:
    def __init__(self, state_dir=None, *, starting_balance=None):

        self.open_trades = []
        self.closed_trades = []

        configured_balance = (
            PAPER_STARTING_BALANCE
            if starting_balance is None
            else float(starting_balance)
        )
        if not math.isfinite(configured_balance) or configured_balance <= 0:
            raise ValueError("Paper starting balance must be a positive number")
        self.starting_balance = float(configured_balance)
        self.balance = self.starting_balance
        self.equity = self.starting_balance
        self.floating_pnl = 0.0

        project_root = Path(__file__).resolve().parents[1]
        configured_state = state_dir or os.getenv("AAQTS_ACCOUNT_STATE_DIR", "")
        account_root = Path(configured_state) if configured_state else project_root
        self.history_file = account_root / "logs" / "trade_history.csv"
        self.trade_file = account_root / "trades.json"

        self.history_file.parent.mkdir(parents=True, exist_ok=True)

        self.load_trades()

        if not os.path.exists(self.history_file):
            with open(self.history_file, "w", newline="") as file:
                writer = csv.writer(file)

                writer.writerow(
                    [
                        "Time",
                        "Symbol",
                        "Side",
                        "Entry",
                        "Exit",
                        "Stop Loss",
                        "Take Profit",
                        "Position",
                        "PnL",
                        "Balance",
                        "Result",
                    ]
                )

    def save_trades(self):

        data = {
            "open_trades": self.open_trades,
            "closed_trades": self.closed_trades,
            "starting_balance": self.starting_balance,
            "balance": self.balance,
        }

        with open(self.trade_file, "w") as file:
            json.dump(data, file, indent=4)

    def load_trades(self):

        if os.path.exists(self.trade_file):
            with open(self.trade_file, "r") as file:
                data = json.load(file)

                self.open_trades = data.get("open_trades", [])

                self.closed_trades = data.get("closed_trades", [])

                stored_starting_balance = float(
                    data.get("starting_balance", self.starting_balance)
                )
                if (
                    not math.isfinite(stored_starting_balance)
                    or stored_starting_balance <= 0
                ):
                    raise ValueError("Stored paper starting balance is invalid")
                self.starting_balance = stored_starting_balance

                self.balance = data.get("balance", self.starting_balance)

                self.equity = self.balance

    def open_trade(self, symbol, signal, entry, stop_loss, take_profit, position):

        for trade in self.open_trades:
            if trade["symbol"] == symbol and trade["status"] == "OPEN":
                return None

        instrument = get_instrument_spec(symbol)
        side = str(signal).upper()
        entry_reference = float(entry)
        entry_fill = instrument.entry_fill_price(entry_reference, side)
        trade = {
            "symbol": symbol,
            "signal": side,
            "entry_reference": entry_reference,
            "entry": entry_fill,
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "position": float(position),
            "status": "OPEN",
            "exit": None,
            "pnl": 0,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }

        self.open_trades.append(trade)

        self.save_trades()

        return trade

    def update_equity(self, prices):

        floating = 0

        for trade in self.open_trades:
            if trade["symbol"] not in prices:
                continue

            current = float(prices[trade["symbol"]])
            instrument = get_instrument_spec(trade["symbol"])
            exit_fill = instrument.exit_fill_price(current, trade["signal"])
            quantity = float(trade["position"])

            if trade["signal"] == "BUY":
                gross = (
                    (exit_fill - float(trade["entry"]))
                    * quantity
                    * instrument.contract_multiplier
                )
                floating += gross - instrument.commission_cost(quantity)

            else:
                gross = (
                    (float(trade["entry"]) - exit_fill)
                    * quantity
                    * instrument.contract_multiplier
                )
                floating += gross - instrument.commission_cost(quantity)

        self.floating_pnl = round(floating, 4)

        self.equity = round(self.balance + self.floating_pnl, 4)

    def check_trade(self, symbol, current_price):

        current_price = float(current_price)

        for trade in self.open_trades[:]:
            if trade["symbol"] != symbol:
                continue
            if (
                float(trade.get("stop_loss", 0.0) or 0.0) <= 0
                and float(trade.get("take_profit", 0.0) or 0.0) <= 0
            ):
                # Signal-to-signal experiments close explicitly on the next
                # opposite signal instead of using price protection.
                continue

            close = False
            stop_loss = float(trade.get("stop_loss", 0.0) or 0.0)
            take_profit = float(trade.get("take_profit", 0.0) or 0.0)

            if trade["signal"] == "BUY":
                if stop_loss > 0 and current_price <= stop_loss:
                    trade["status"] = "STOP LOSS"

                    close = True

                elif take_profit > 0 and current_price >= take_profit:
                    trade["status"] = "TAKE PROFIT"

                    close = True

                if close:
                    instrument = get_instrument_spec(trade["symbol"])
                    exit_fill = instrument.exit_fill_price(
                        current_price, trade["signal"]
                    )
                    quantity = float(trade["position"])
                    trade["exit_reference"] = current_price
                    trade["exit"] = exit_fill
                    gross = (
                        (exit_fill - float(trade["entry"]))
                        * quantity
                        * instrument.contract_multiplier
                    )
                    trade["pnl"] = round(
                        gross - instrument.commission_cost(quantity), 4
                    )

            else:
                if stop_loss > 0 and current_price >= stop_loss:
                    trade["status"] = "STOP LOSS"

                    close = True

                elif take_profit > 0 and current_price <= take_profit:
                    trade["status"] = "TAKE PROFIT"

                    close = True

                if close:
                    instrument = get_instrument_spec(trade["symbol"])
                    exit_fill = instrument.exit_fill_price(
                        current_price, trade["signal"]
                    )
                    quantity = float(trade["position"])
                    trade["exit_reference"] = current_price
                    trade["exit"] = exit_fill
                    gross = (
                        (float(trade["entry"]) - exit_fill)
                        * quantity
                        * instrument.contract_multiplier
                    )
                    trade["pnl"] = round(
                        gross - instrument.commission_cost(quantity), 4
                    )

            if close:
                trade["closed_at"] = datetime.now(timezone.utc).isoformat()

                self.balance = round(self.balance + trade["pnl"], 4)

                self.equity = self.balance
                self.floating_pnl = 0.0

                print("\nTrade Closed")
                print(f"Symbol : {trade['symbol']}")
                print(f"Result : {trade['status']}")
                print(f"P/L    : {trade['pnl']}")
                print(f"Balance: {self.balance}")

                self.closed_trades.append(trade)

                self.save_trade_history(trade)

                self.open_trades.remove(trade)

                self.save_trades()

    def close_trade_on_signal(self, symbol, next_side, current_price=None):
        """Close one opposite paper trade at the next signal event."""

        wanted = str(next_side).upper().strip()
        if wanted not in {"BUY", "SELL"}:
            raise ValueError("next_side must be BUY or SELL")
        for trade in self.open_trades[:]:
            if trade["symbol"] != symbol or trade["signal"] == wanted:
                continue
            reference = float(
                current_price
                if current_price is not None
                else trade.get("last_price", trade["entry_reference"])
            )
            instrument = get_instrument_spec(trade["symbol"])
            exit_fill = instrument.exit_fill_price(reference, trade["signal"])
            quantity = float(trade["position"])
            if trade["signal"] == "BUY":
                gross = (
                    (exit_fill - float(trade["entry"]))
                    * quantity
                    * instrument.contract_multiplier
                )
            else:
                gross = (
                    (float(trade["entry"]) - exit_fill)
                    * quantity
                    * instrument.contract_multiplier
                )
            trade.update(
                {
                    "status": "OPPOSITE SIGNAL",
                    "exit_reference": reference,
                    "exit": exit_fill,
                    "pnl": round(
                        gross - instrument.commission_cost(quantity), 4
                    ),
                    "closed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self.balance = round(self.balance + trade["pnl"], 4)
            self.equity = self.balance
            self.floating_pnl = 0.0
            self.closed_trades.append(trade)
            self.open_trades.remove(trade)
            self.save_trade_history(trade)
            self.save_trades()
            return trade
        return None

    def save_trade_history(self, trade):

        with open(self.history_file, "a", newline="") as file:
            writer = csv.writer(file)

            writer.writerow(
                [
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    trade["symbol"],
                    trade["signal"],
                    trade["entry"],
                    trade["exit"],
                    trade["stop_loss"],
                    trade["take_profit"],
                    trade["position"],
                    trade["pnl"],
                    self.balance,
                    trade["status"],
                ]
            )

    def get_stats(self):

        total = len(self.closed_trades)

        wins = len([t for t in self.closed_trades if float(t.get("pnl", 0.0)) > 0])

        total_pnl = round(sum(t["pnl"] for t in self.closed_trades), 4)

        win_rate = 0

        if total > 0:
            win_rate = round((wins / total) * 100, 2)

        return {
            "starting_balance": self.starting_balance,
            "balance": self.balance,
            "equity": self.equity,
            "floating_pnl": self.floating_pnl,
            "total_trades": total,
            "wins": wins,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
        }
