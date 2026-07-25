class PerformanceTracker:

    def __init__(self):

        self.closed_trades = []

    def add_trade(self, trade):

        self.closed_trades.append(trade)

    def get_report(self):

        total = len(self.closed_trades)

        wins = [
            t for t in self.closed_trades
            if t["pnl"] > 0
        ]

        losses = [
            t for t in self.closed_trades
            if t["pnl"] <= 0
        ]

        gross_profit = round(
            sum(t["pnl"] for t in wins),
            4
        )

        gross_loss = round(
            abs(sum(t["pnl"] for t in losses)),
            4
        )

        net_profit = round(
            gross_profit - gross_loss,
            4
        )

        win_rate = 0

        if total > 0:
            win_rate = round(
                (len(wins) / total) * 100,
                2
            )

        average_win = 0

        if wins:
            average_win = round(
                gross_profit / len(wins),
                4
            )

        average_loss = 0

        if losses:
            average_loss = round(
                gross_loss / len(losses),
                4
            )

        if gross_loss == 0:
            profit_factor = float("inf") if gross_profit > 0 else 0
        else:
            profit_factor = round(
                gross_profit / gross_loss,
                4
            )

        expectancy = 0

        if total > 0:
            expectancy = round(
                net_profit / total,
                4
            )

        return {

            "total_trades": total,

            "wins": len(wins),

            "losses": len(losses),

            "win_rate": win_rate,

            "gross_profit": gross_profit,

            "gross_loss": gross_loss,

            "average_win": average_win,

            "average_loss": average_loss,

            "profit_factor": profit_factor,

            "expectancy": expectancy,

            "net_profit": net_profit
        }