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


        for index, row in self.data.iterrows():

            price = row["Close"]
            atr = row["ATR"]

            signal = self.strategy(row)


            if position is None:

                if signal == "BUY":

                    position = "LONG"
                    entry_price = price

                    stop_loss = price - (2 * atr)
                    take_profit = price + (3 * atr)


                    self.trades.append({
                        "type": "BUY",
                        "price": price,
                        "time": index
                    })


            else:

                if price <= stop_loss or price >= take_profit or signal == "SELL":

                    profit = price - entry_price


                    self.trades.append({
                        "type": "SELL",
                        "price": price,
                        "profit": profit,
                        "time": index
                    })


                    position = None
                    entry_price = None
                    stop_loss = None
                    take_profit = None


        return self.trades
