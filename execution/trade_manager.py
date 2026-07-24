class TradeManager:

    def __init__(self):
        pass

    def calculate_trade(self, data, signal):

        current_price = data["Close"].iloc[-1]
        atr = data["ATR"].iloc[-1]

        return {
            "current_price": current_price,
            "atr": atr
        }