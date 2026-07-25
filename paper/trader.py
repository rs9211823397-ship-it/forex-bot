from paper.account import PaperAccount
from paper.journal import TradeJournal
from paper.performance import PerformanceTracker


class PaperTrader:

    def __init__(self):

        self.account = PaperAccount()

        self.journal = TradeJournal()

        self.performance = PerformanceTracker()

        self.open_trades = []

        self.trade_id = 1


    def open_trade(
        self,
        symbol,
        signal,
        entry,
        stop_loss,
        take_profit
    ):

        signal = signal.upper()

        if signal not in ["BUY", "SELL"]:
            return None


        for trade in self.open_trades:

            if (
                trade["symbol"] == symbol
                and trade["status"] == "OPEN"
            ):
                return None


        trade = {

            "id": self.trade_id,

            "symbol": symbol,

            "signal": signal,

            "entry": float(entry),

            "stop_loss": float(stop_loss),

            "take_profit": float(take_profit),

            "status": "OPEN",

            "exit": None,

            "pnl": 0
        }


        self.trade_id += 1


        self.open_trades.append(trade)


        print("\nTrade Opened")
        print(f"ID     : {trade['id']}")
        print(f"Symbol : {symbol}")
        print(f"Signal : {signal}")
        print(f"Entry  : {entry}")


        return trade



    def check_trade(
        self,
        symbol,
        current_price
    ):

        current_price = float(current_price)


        for trade in self.open_trades[:]:


            if trade["symbol"] != symbol:
                continue


            closed = False



            if trade["signal"] == "BUY":


                if current_price <= trade["stop_loss"]:

                    trade["status"] = "STOP LOSS"

                    trade["exit"] = current_price

                    trade["pnl"] = round(
                        current_price - trade["entry"],
                        4
                    )

                    closed = True



                elif current_price >= trade["take_profit"]:

                    trade["status"] = "TAKE PROFIT"

                    trade["exit"] = current_price

                    trade["pnl"] = round(
                        current_price - trade["entry"],
                        4
                    )

                    closed = True




            elif trade["signal"] == "SELL":


                if current_price >= trade["stop_loss"]:

                    trade["status"] = "STOP LOSS"

                    trade["exit"] = current_price

                    trade["pnl"] = round(
                        trade["entry"] - current_price,
                        4
                    )

                    closed = True



                elif current_price <= trade["take_profit"]:

                    trade["status"] = "TAKE PROFIT"

                    trade["exit"] = current_price

                    trade["pnl"] = round(
                        trade["entry"] - current_price,
                        4
                    )

                    closed = True



            if not closed:
                continue



            self.account.update_balance(
                trade["pnl"]
            )


            self.performance.add_trade(
                trade
            )


            account = self.account.get_account_info()


            self.journal.save_trade(
                trade,
                account["balance"]
            )



            print("\nTrade Closed")
            print(f"Symbol  : {trade['symbol']}")
            print(f"Result  : {trade['status']}")
            print(f"Entry   : {trade['entry']}")
            print(f"Exit    : {trade['exit']}")
            print(f"P/L     : {trade['pnl']}")
            print(f"Balance : {account['balance']}")



            self.open_trades.remove(
                trade
            )



    def update_equity(self, prices):

        floating = 0


        for trade in self.open_trades:


            if trade["symbol"] not in prices:
                continue


            current = float(
                prices[trade["symbol"]]
            )


            if trade["signal"] == "BUY":

                floating += (
                    current - trade["entry"]
                )


            else:

                floating += (
                    trade["entry"] - current
                )



        self.account.update_equity(
            floating
        )



    def get_account(self):

        return self.account.get_account_info()



    def get_performance(self):

        return self.performance.get_report()
    