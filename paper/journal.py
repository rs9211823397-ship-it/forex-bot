import csv
import os
from datetime import datetime


class TradeJournal:

    def __init__(self, history_file="logs/trade_history.csv"):

        self.history_file = history_file

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

    def save_trade(self, trade, balance):

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
                balance,
                trade["status"]
            ])

    def get_history_file(self):

        return self.history_file