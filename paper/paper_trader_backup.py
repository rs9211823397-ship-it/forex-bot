import csv
import os
import json
from datetime import datetime


class PaperTrader:

    def __init__(self):

        self.open_trades = []
        self.closed_trades = []
        self.trade_file = "trades.json"

        self.load_trades()

        # Account
        self.starting_balance = 1000.0
        self.balance = self.starting_balance
        self.equity = self.starting_balance
        self.floating_pnl = 0.0

        self.history_file = "logs/trade_history.csv"

        os.makedirs("logs", exist_ok=True)

        if not os.path.exists(self.history_file):
            with open(self.history_file, "w", newline="") as file:

                writer = csv.writer(file)

                writer.writerow([
                    "Time",
                    "Symbol",
                    "Side",
                    "Entry",
                    "Exit",
                    "Stop Loss",
                    "Take Profit",
                    "PnL",
                    "Balance",
                    "Result"
                ])

    def open_trade(self, symbol, signal, entry, stop_loss, take_profit):

        for trade in self.open_trades:
            if trade["symbol"] == symbol and trade["status"] == "OPEN":
                return None

        trade = {
            "symbol": symbol,
            "signal": signal,
            "entry": float(entry),
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "status": "OPEN",
            "exit": None,
            "pnl": 0
        }

        self.open_trades.append(trade)
        return trade

    def update_equity(self, prices):

        floating = 0

        for trade in self.open_trades:

            if trade["symbol"] not in prices:
                continue

            current = prices[trade["symbol"]]

            if trade["signal"] == "BUY":
                floating += current - trade["entry"]
            else:
                floating += trade["entry"] - current

        self.floating_pnl = round(floating, 4)
        self.equity = round(
            self.balance + self.floating_pnl,
            4
        )

    def check_trade(self, symbol, current_price):

        current_price = float(current_price)

        for trade in self.open_trades[:]:

            if trade["symbol"] != symbol:
                continue

            if trade["signal"] == "BUY":

                if current_price <= trade["stop_loss"]:

                    trade["status"] = "STOP LOSS"
                    trade["exit"] = current_price
                    trade["pnl"] = round(
                        current_price - trade["entry"],
                        4
                    )

                elif current_price >= trade["take_profit"]:

                    trade["status"] = "TAKE PROFIT"
                    trade["exit"] = current_price
                    trade["pnl"] = round(
                        current_price - trade["entry"],
                        4
                    )

                else:
                    continue

            else:

                if current_price >= trade["stop_loss"]:

                    trade["status"] = "STOP LOSS"
                    trade["exit"] = current_price
                    trade["pnl"] = round(
                        trade["entry"] - current_price,
                        4
                    )

                elif current_price <= trade["take_profit"]:

                    trade["status"] = "TAKE PROFIT"
                    trade["exit"] = current_price
                    trade["pnl"] = round(
                        trade["entry"] - current_price,
                        4
                    )

                else:
                    continue

            # Update Account Balance
            self.balance = round(
                self.balance + trade["pnl"],
                4
            )

            print("\nTrade Closed")
            print(f"Symbol : {trade['symbol']}")
            print(f"Result : {trade['status']}")
            print(f"P/L    : {trade['pnl']}")
            print(f"Balance: {self.balance}")

            self.closed_trades.append(trade)

            self.save_trade_history(trade)

            self.open_trades.remove(trade)

    def save_trade_history(self, trade):

        with open(self.history_file, "a", newline="") as file:

            writer = csv.writer(file)

            writer.writerow([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                trade["symbol"],
                trade["signal"],
                trade["entry"],
                trade["exit"],
                trade["stop_loss"],
                trade["take_profit"],
                trade["pnl"],
                self.balance,
                trade["status"]
            ])

        def save_trades(self):

        data = {
            "open_trades": self.open_trades,
            "closed_trades": self.closed_trades
        }

        with open(self.trade_file, "w") as file:
            json.dump(data, file, indent=4)



    def load_trades(self):

        if os.path.exists(self.trade_file):

            with open(self.trade_file, "r") as file:

                data = json.load(file)

                self.open_trades = data.get(
                    "open_trades",
                    []
                )

                self.closed_trades = data.get(
                    "closed_trades",
                    []
                )



    def get_stats(self):

        total = len(self.closed_trades)

        wins = len([
            t for t in self.closed_trades
            if t["status"] == "TAKE PROFIT"
        ])

        total_pnl = round(
            sum(t["pnl"] for t in self.closed_trades),
            4
        )

        win_rate = 0

        if total > 0:
            win_rate = round(
                (wins / total) * 100,
                2
            )

        return {
            "starting_balance": self.starting_balance,
            "balance": round(self.balance, 4),
            "equity": round(self.equity, 4),
            "floating_pnl": round(self.floating_pnl, 4),
            "total_trades": total,
            "wins": wins,
            "win_rate": win_rate,
            "total_pnl": total_pnl
        }