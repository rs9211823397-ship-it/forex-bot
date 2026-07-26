class BacktestEngine:

    def __init__(self, data, strategy):
        self.data = data
        self.strategy = strategy
        self.trades = []

    def run(self):

        position = None
        entry_price = None
        stop_loss = None
        take_profit = None

        for i, (index, row) in enumerate(self.data.iterrows()):

            price = row["close"]
            atr = row["ATR"]
            adx = row["ADX"]

            signal = self.strategy(i)

            # ==========================
            # Dynamic ATR Multipliers
            # ==========================

            if adx >= 40:
                sl_mult = 2.5
                tp_mult = 4.5

            elif adx >= 30:
                sl_mult = 2.0
                tp_mult = 4.0

            else:
                sl_mult = 1.5
                tp_mult = 3.0

            if position is None:

                if signal == "BUY":

                    position = "LONG"
                    entry_price = price

                    stop_loss = price - (sl_mult * atr)
                    take_profit = price + (tp_mult * atr)

                    self.trades.append({
                        "type": "BUY",
                        "price": price,
                        "time": index
                    })

                elif signal == "SELL":

                    position = "SHORT"
                    entry_price = price

                    stop_loss = price + (sl_mult * atr)
                    take_profit = price - (tp_mult * atr)

                    self.trades.append({
                        "type": "SELL",
                        "price": price,
                        "time": index
                    })

            else:

                exit_trade = False

                if position == "LONG":

                    if (
                        price <= stop_loss
                        or price >= take_profit
                        or signal == "SELL"
                    ):
                        profit = price - entry_price
                        exit_trade = True

                elif position == "SHORT":

                    if (
                        price >= stop_loss
                        or price <= take_profit
                        or signal == "BUY"
                    ):
                        profit = entry_price - price
                        exit_trade = True

                if exit_trade:

                    self.trades.append({
                        "type": "EXIT",
                        "price": price,
                        "profit": profit,
                        "time": index
                    })

                    position = None
                    entry_price = None
                    stop_loss = None
                    take_profit = None

        return self.trades
