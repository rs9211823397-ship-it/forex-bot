class PerformanceReport:

    def __init__(self, trades):
        self.trades = trades


    def total_trades(self):

        return len([
            t for t in self.trades
            if t["type"] == "SELL"
        ])


    def winning_trades(self):

        return len([
            t for t in self.trades
            if t["type"] == "SELL"
            and t.get("profit", 0) > 0
        ])


    def losing_trades(self):

        return len([
            t for t in self.trades
            if t["type"] == "SELL"
            and t.get("profit", 0) <= 0
        ])


    def win_rate(self):

        total = self.total_trades()

        if total == 0:
            return 0

        return round(
            (self.winning_trades() / total) * 100,
            2
        )


    def total_profit(self):

        return round(
            float(sum(
                t.get("profit", 0)
                for t in self.trades
            )),
            2
        )


    def summary(self):

        return {
            "Completed Trades": self.total_trades(),
            "Winning Trades": self.winning_trades(),
            "Losing Trades": self.losing_trades(),
            "Win Rate %": self.win_rate(),
            "Net Profit": self.total_profit()
        }
