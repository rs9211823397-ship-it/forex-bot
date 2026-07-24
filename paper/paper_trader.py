class PaperTrader:

    def __init__(self):
        self.open_trades = []
        self.closed_trades = []


    def open_trade(self, symbol, signal, entry, stop_loss, take_profit):

        for trade in self.open_trades:
            if trade["symbol"] == symbol:
                return trade

        trade = {
            "symbol": symbol,
            "signal": signal,
            "entry": float(entry),
            "stop_loss": float(stop_loss),
            "take_profit": float(take_profit),
            "status": "OPEN",
            "pnl": 0
        }

        self.open_trades.append(trade)

        return trade


    def check_trade(self, current_price):

        for trade in self.open_trades[:]:

            current_price = float(current_price)

            if trade["signal"] == "BUY":

                if current_price <= trade["stop_loss"]:
                    trade["status"] = "STOP LOSS"
                    trade["pnl"] = round(
                        current_price - trade["entry"], 4
                    )

                    self.closed_trades.append(trade)
                    self.open_trades.remove(trade)


                elif current_price >= trade["take_profit"]:
                    trade["status"] = "TAKE PROFIT"
                    trade["pnl"] = round(
                        current_price - trade["entry"], 4
                    )

                    self.closed_trades.append(trade)
                    self.open_trades.remove(trade)


            elif trade["signal"] == "SELL":

                if current_price >= trade["stop_loss"]:
                    trade["status"] = "STOP LOSS"
                    trade["pnl"] = round(
                        trade["entry"] - current_price, 4
                    )

                    self.closed_trades.append(trade)
                    self.open_trades.remove(trade)


                elif current_price <= trade["take_profit"]:
                    trade["status"] = "TAKE PROFIT"
                    trade["pnl"] = round(
                        trade["entry"] - current_price, 4
                    )

                    self.closed_trades.append(trade)
                    self.open_trades.remove(trade)



    def get_stats(self):

        total = len(self.closed_trades)

        wins = len(
            [
                t for t in self.closed_trades
                if t["status"] == "TAKE PROFIT"
            ]
        )

        total_pnl = round(
            sum(t["pnl"] for t in self.closed_trades),
            4
        )

        win_rate = 0

        if total > 0:
            win_rate = round((wins / total) * 100, 2)


        return {
            "total_trades": total,
            "wins": wins,
            "win_rate": win_rate,
            "total_pnl": total_pnl
        }