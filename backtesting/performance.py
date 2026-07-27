"""Performance metrics over completed, cash-accounted backtest trades."""

from math import inf, isclose, isfinite

from config.settings import ACCOUNT_BALANCE


class PerformanceReport:

    def __init__(
        self,
        trades,
        initial_equity=None,
        equity_curve=None
    ):
        self.trades = trades
        self.provided_equity_curve = (
            [float(value) for value in equity_curve]
            if equity_curve is not None
            else None
        )

        if (
            self.provided_equity_curve is not None
            and not self.provided_equity_curve
        ):
            raise ValueError(
                "Provided equity curve cannot be empty"
            )

        if (
            self.provided_equity_curve is not None
            and not all(
                isfinite(value)
                for value in self.provided_equity_curve
            )
        ):
            raise ValueError(
                "Provided equity curve must contain finite values"
            )

        self.initial_equity = self._resolve_initial_equity(
            initial_equity
        )

        if (
            not isfinite(self.initial_equity)
            or self.initial_equity <= 0
        ):
            raise ValueError(
                "initial_equity must be finite and greater than zero"
            )

        if (
            self.provided_equity_curve is not None
            and not isclose(
                self.provided_equity_curve[0],
                self.initial_equity,
                rel_tol=0.0,
                abs_tol=1e-9
            )
        ):
            raise ValueError(
                "Equity curve must begin at initial_equity"
            )

    def _resolve_initial_equity(self, requested_equity):
        if requested_equity is not None:
            return float(requested_equity)

        if self.provided_equity_curve is not None:
            return self.provided_equity_curve[0]

        for trade in self.trades:
            if trade.get("type") != "EXIT":
                continue

            if trade.get("starting_equity") is not None:
                return float(trade["starting_equity"])

            if (
                trade.get("equity") is not None
                and trade.get("profit") is not None
            ):
                return (
                    float(trade["equity"])
                    - float(trade["profit"])
                )

        return float(ACCOUNT_BALANCE)

    def completed_trades(self):
        return [
            trade for trade in self.trades
            if trade["type"] == "EXIT"
        ]

    def total_trades(self):
        return len(self.completed_trades())

    def winning_trades(self):
        return [
            trade for trade in self.completed_trades()
            if float(trade["profit"]) > 0
        ]

    def losing_trades(self):
        return [
            trade for trade in self.completed_trades()
            if float(trade["profit"]) < 0
        ]

    def breakeven_trades(self):
        return [
            trade for trade in self.completed_trades()
            if float(trade["profit"]) == 0
        ]

    def win_rate(self):
        total = self.total_trades()

        if total == 0:
            return 0

        return len(self.winning_trades()) / total * 100.0

    def gross_profit(self):
        return sum(
            float(trade["profit"])
            for trade in self.winning_trades()
        )

    def gross_loss(self):
        return abs(sum(
            float(trade["profit"])
            for trade in self.losing_trades()
        ))

    def total_profit(self):
        return sum(
            float(trade["profit"])
            for trade in self.completed_trades()
        )

    def average_win(self):
        wins = self.winning_trades()

        if not wins:
            return 0

        return sum(
            float(trade["profit"])
            for trade in wins
        ) / len(wins)

    def average_loss(self):
        losses = self.losing_trades()

        if not losses:
            return 0

        return sum(
            float(trade["profit"])
            for trade in losses
        ) / len(losses)

    def profit_factor(self):
        wins = self.gross_profit()
        losses = self.gross_loss()

        if losses == 0:
            return inf if wins > 0 else 0

        return wins / losses

    def expectancy(self):
        total = self.total_trades()

        if total == 0:
            return 0

        return self.total_profit() / total

    def average_r(self):
        multiples = [
            float(trade["r_multiple"])
            for trade in self.completed_trades()
            if trade.get("r_multiple") is not None
        ]

        if not multiples:
            return 0

        return sum(multiples) / len(multiples)

    def payoff_ratio(self):
        average_win = self.average_win()
        average_loss = abs(self.average_loss())

        if average_loss == 0:
            return inf if average_win > 0 else 0

        return average_win / average_loss

    def equity_curve(self):
        if self.provided_equity_curve is not None:
            return self.provided_equity_curve[1:]

        running_equity = self.initial_equity
        curve = []

        for trade in self.completed_trades():
            if trade.get("equity") is not None:
                running_equity = float(trade["equity"])
            else:
                running_equity += float(trade["profit"])

            curve.append(running_equity)

        return curve

    def _equity_path(self):
        if self.provided_equity_curve is not None:
            return list(self.provided_equity_curve)

        return [
            self.initial_equity,
            *self.equity_curve()
        ]

    def max_drawdown(self):
        path = self._equity_path()

        if len(path) < 2:
            return 0

        peak = path[0]
        maximum_drawdown = 0.0

        for value in path[1:]:
            peak = max(peak, value)
            maximum_drawdown = max(
                maximum_drawdown,
                peak - value
            )

        return maximum_drawdown

    def max_drawdown_percent(self):
        path = self._equity_path()

        if len(path) < 2:
            return 0

        peak = path[0]
        maximum_percent = 0.0

        for value in path[1:]:
            peak = max(peak, value)

            if peak > 0:
                maximum_percent = max(
                    maximum_percent,
                    (peak - value) / peak * 100.0
                )

        return maximum_percent

    def ending_equity(self):
        curve = self.equity_curve()

        if curve:
            return curve[-1]

        return self.initial_equity

    def open_trades(self):
        entries = sum(
            1 for trade in self.trades
            if trade["type"] == "ENTRY"
        )
        exits = self.total_trades()
        return max(entries - exits, 0)

    def strategy_rating(self):
        profit_factor = self.profit_factor()

        if profit_factor >= 2:
            return "A"

        if profit_factor >= 1.5:
            return "B"

        if profit_factor >= 1:
            return "C"

        return "FAIL"

    def summary(self):
        return {
            "Completed Trades": self.total_trades(),
            "Winning Trades": len(self.winning_trades()),
            "Losing Trades": len(self.losing_trades()),
            "Breakeven Trades": len(self.breakeven_trades()),
            "Win Rate %": round(self.win_rate(), 2),
            "Gross Profit": round(self.gross_profit(), 4),
            "Gross Loss": round(self.gross_loss(), 4),
            "Net Profit": round(self.total_profit(), 4),
            "Average Win": round(self.average_win(), 4),
            "Average Loss": round(self.average_loss(), 4),
            "Profit Factor": (
                self.profit_factor()
                if self.profit_factor() == inf
                else round(self.profit_factor(), 4)
            ),
            "Expectancy": round(self.expectancy(), 4),
            "Average R": round(self.average_r(), 4),
            "Payoff Ratio": (
                self.payoff_ratio()
                if self.payoff_ratio() == inf
                else round(self.payoff_ratio(), 4)
            ),
            "Max Drawdown": round(self.max_drawdown(), 4),
            "Max Drawdown %": round(
                self.max_drawdown_percent(),
                4
            ),
            "Ending Equity": round(self.ending_equity(), 4),
            "Open Trades": self.open_trades(),
            "Strategy Rating": self.strategy_rating()
        }
