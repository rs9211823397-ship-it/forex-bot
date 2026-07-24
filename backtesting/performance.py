class PerformanceReport:

    def __init__(self, trades):
        self.trades = trades


    def completed_trades(self):

        return [
            t for t in self.trades
            if t["type"] == "SELL"
        ]


    def total_trades(self):

        return len(self.completed_trades())


    def winning_trades(self):

        return [
            t for t in self.completed_trades()
            if t.get("profit", 0) > 0
        ]


    def losing_trades(self):

        return [
            t for t in self.completed_trades()
            if t.get("profit", 0) <= 0
        ]


    def win_rate(self):

        total = self.total_trades()

        if total == 0:
            return 0

        return round(
            (len(self.winning_trades()) / total) * 100,
            2
        )


    def total_profit(self):

        return round(
            float(sum(
                t.get("profit", 0)
                for t in self.completed_trades()
            )),
            2
        )


    def average_win(self):

        wins = self.winning_trades()

        if not wins:
            return 0

        return round(
            float(sum(t["profit"] for t in wins) / len(wins)),
            2
        )


    def average_loss(self):

        losses = self.losing_trades()

        if not losses:
            return 0

        return round(
            float(sum(t["profit"] for t in losses) / len(losses)),
            2
        )


    def profit_factor(self):

        total_win = sum(
            t["profit"]
            for t in self.winning_trades()
        )

        total_loss = abs(sum(
            t["profit"]
            for t in self.losing_trades()
        ))

        if total_loss == 0:
            return 0

        return round(
            float(total_win / total_loss),
            2
        )


    def equity_curve(self):

        balance = 0
        curve = []

        for trade in self.completed_trades():

            balance += float(trade.get("profit", 0))
            curve.append(balance)

        return curve


    def max_drawdown(self):

        curve = self.equity_curve()

        if not curve:
            return 0

        peak = curve[0]
        max_dd = 0

        for value in curve:

            if value > peak:
                peak = value

            drawdown = peak - value

            if drawdown > max_dd:
                max_dd = drawdown

        return round(max_dd, 2)


    def strategy_rating(self):

        pf = self.profit_factor()

        if pf >= 2:
            return "A"

        elif pf >= 1.5:
            return "B"

        elif pf >= 1:
            return "C"

        else:
            return "FAIL"


    def summary(self):

        return {
            "Completed Trades": self.total_trades(),
            "Winning Trades": len(self.winning_trades()),
            "Losing Trades": len(self.losing_trades()),
            "Win Rate %": self.win_rate(),
            "Net Profit": self.total_profit(),
            "Average Win": self.average_win(),
            "Average Loss": self.average_loss(),
            "Profit Factor": self.profit_factor(),
            "Max Drawdown": self.max_drawdown(),
            "Strategy Rating": self.strategy_rating()
        }
