class RiskManager:

    def __init__(self, risk_percent=1, reward_ratio=2):
        self.risk_percent = risk_percent
        self.reward_ratio = reward_ratio


    def calculate_trade_levels(self, signal, entry_price, atr):

        if signal == "BUY":

            stop_loss = entry_price - (atr * 1.5)
            take_profit = entry_price + (atr * 3)

        elif signal == "SELL":

            stop_loss = entry_price + (atr * 1.5)
            take_profit = entry_price - (atr * 3)

        else:
            return None


        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)

        risk_reward = round(reward / risk, 2)


        return {
            "entry": round(entry_price, 5),
            "stop_loss": round(stop_loss, 5),
            "take_profit": round(take_profit, 5),
            "risk_reward": risk_reward
        }


    def position_size(self, account_balance, entry_price, stop_loss):

        risk_amount = account_balance * (self.risk_percent / 100)

        price_risk = abs(entry_price - stop_loss)

        if price_risk == 0:
            return 0

        size = risk_amount / price_risk

        return round(size, 4)