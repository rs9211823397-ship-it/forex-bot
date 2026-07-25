from paper.trader import PaperTrader


class PaperEngine:

    def __init__(self):

        self.trader = PaperTrader()

    def open_trade(
        self,
        symbol,
        signal,
        entry,
        stop_loss,
        take_profit
    ):

        return self.trader.open_trade(
            symbol,
            signal,
            entry,
            stop_loss,
            take_profit
        )

    def check_trade(
        self,
        symbol,
        current_price
    ):

        self.trader.check_trade(
            symbol,
            current_price
        )

    def update_equity(
        self,
        prices
    ):

        self.trader.update_equity(
            prices
        )

    def get_account(self):

        return self.trader.get_account()

    def get_performance(self):

        return self.trader.get_performance()

    def get_open_trades(self):

        return self.trader.open_trades