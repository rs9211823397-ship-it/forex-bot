import math
from statistics import mean, pstdev


class PerformanceReport:
    def __init__(self, trades, initial_balance=10_000.0, periods_per_year=252):
        self.trades = list(trades)
        self.initial_balance = float(initial_balance)
        self.periods_per_year = periods_per_year

    def completed_trades(self):
        return self.trades

    def total_trades(self):
        return len(self.trades)

    def winning_trades(self):
        return [trade for trade in self.trades if trade.get("net_pnl", 0) > 0]

    def losing_trades(self):
        return [trade for trade in self.trades if trade.get("net_pnl", 0) <= 0]

    def win_rate(self):
        return round(len(self.winning_trades()) / len(self.trades) * 100, 2) if self.trades else 0.0

    def total_profit(self):
        return round(sum(trade.get("net_pnl", 0) for trade in self.trades), 2)

    def average_win(self):
        wins = [trade["net_pnl"] for trade in self.winning_trades()]
        return round(mean(wins), 2) if wins else 0.0

    def average_loss(self):
        losses = [trade["net_pnl"] for trade in self.losing_trades()]
        return round(mean(losses), 2) if losses else 0.0

    def profit_factor(self):
        gross_profit = sum(trade["net_pnl"] for trade in self.winning_trades())
        gross_loss = abs(sum(trade["net_pnl"] for trade in self.losing_trades()))
        if gross_loss == 0:
            return math.inf if gross_profit > 0 else 0.0
        return round(gross_profit / gross_loss, 2)

    def equity_curve(self):
        balance = self.initial_balance
        curve = [balance]
        for trade in self.trades:
            balance += trade.get("net_pnl", 0)
            curve.append(balance)
        return curve

    def max_drawdown(self):
        peak = self.initial_balance
        max_amount = 0.0
        max_percent = 0.0
        for value in self.equity_curve():
            peak = max(peak, value)
            drawdown = peak - value
            percent = drawdown / peak if peak else 0.0
            max_amount = max(max_amount, drawdown)
            max_percent = max(max_percent, percent)
        return {
            "amount": round(max_amount, 2),
            "percent": round(max_percent * 100, 2),
        }

    def returns(self):
        curve = self.equity_curve()
        return [
            (current - previous) / previous
            for previous, current in zip(curve, curve[1:])
            if previous
        ]

    def sharpe_ratio(self, risk_free_rate=0.0):
        returns = self.returns()
        if len(returns) < 2 or pstdev(returns) == 0:
            return 0.0
        excess = mean(returns) - risk_free_rate / self.periods_per_year
        return round(excess / pstdev(returns) * math.sqrt(self.periods_per_year), 2)

    def sortino_ratio(self, target_return=0.0):
        returns = self.returns()
        downside = [min(value - target_return, 0.0) for value in returns]
        downside_deviation = math.sqrt(mean([value * value for value in downside])) if downside else 0.0
        if downside_deviation == 0:
            return 0.0
        return round((mean(returns) - target_return) / downside_deviation * math.sqrt(self.periods_per_year), 2)

    def calmar_ratio(self):
        drawdown = self.max_drawdown()["percent"] / 100
        if drawdown == 0:
            return 0.0
        total_return = self.total_profit() / self.initial_balance
        return round(total_return / drawdown, 2)

    def expectancy(self):
        if not self.trades:
            return 0.0
        win_probability = len(self.winning_trades()) / len(self.trades)
        loss_probability = 1 - win_probability
        return round(
            win_probability * self.average_win()
            + loss_probability * self.average_loss(),
            2,
        )

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
            "Expectancy": self.expectancy(),
            "Max Drawdown": self.max_drawdown(),
            "Sharpe Ratio": self.sharpe_ratio(),
            "Sortino Ratio": self.sortino_ratio(),
            "Calmar Ratio": self.calmar_ratio(),
        }
