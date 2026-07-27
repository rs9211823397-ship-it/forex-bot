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
        entry_time = None

        for i, (index, row) in enumerate(self.data.iterrows()):

            price = row["close"]
            atr = row["ATR"]
            adx = row["ADX"]

            signal = self.strategy(i)

            # ==========================
            # Dynamic ATR Multipliers
            # ==========================

            if adx >= 40:
                sl_mult = 2.0
                tp_mult = 3.5

            elif adx >= 30:
                sl_mult = 1.8
                tp_mult = 3.0

            else:
                sl_mult = 1.5
                tp_mult = 2.5


            if position is None:

                if signal == "BUY":

                    position = "LONG"
                    entry_price = price
                    entry_time = index

                    stop_loss = price - (sl_mult * atr)
                    take_profit = price + (tp_mult * atr)

                    self.trades.append({
                        "type": "ENTRY",
                        "side": "BUY",
                        "price": price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "time": index
                    })


                elif signal == "SELL":

                    position = "SHORT"
                    entry_price = price
                    entry_time = index

                    stop_loss = price + (sl_mult * atr)
                    take_profit = price - (tp_mult * atr)

                    self.trades.append({
                        "type": "ENTRY",
                        "side": "SELL",
                        "price": price,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "time": index
                    })


            else:

                exit_trade = False
                result = None

                if position == "LONG":

                    if price <= stop_loss:

                        profit = price - entry_price
                        exit_trade = True
                        result = "STOP LOSS"


                    elif price >= take_profit:

                        profit = price - entry_price
                        exit_trade = True
                        result = "TAKE PROFIT"



                elif position == "SHORT":

                    if price >= stop_loss:

                        profit = entry_price - price
                        exit_trade = True
                        result = "STOP LOSS"


                    elif price <= take_profit:

                        profit = entry_price - price
                        exit_trade = True
                        result = "TAKE PROFIT"



                if exit_trade:

                    self.trades.append({
                        "type": "EXIT",
                        "side": position,
                        "entry_price": entry_price,
                        "exit_price": price,
                        "profit": profit,
                        "result": result,
                        "entry_time": entry_time,
                        "exit_time": index
                    })


                    position = None
                    entry_price = None
                    stop_loss = None
                    take_profit = None
                    entry_time = None


        return self.trades
