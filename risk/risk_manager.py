from config.settings import RISK_PERCENT
from math import isfinite
from risk.instrument import InstrumentSpec


class RiskManager:

    def __init__(self, risk_percent=RISK_PERCENT, reward_ratio=2):
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


    def position_size(
        self,
        account_balance,
        entry_price,
        stop_loss,
        instrument=None,
        side=None
    ):

        risk_amount = account_balance * (self.risk_percent / 100)

        price_risk = abs(entry_price - stop_loss)

        if (
            not isfinite(float(risk_amount))
            or risk_amount <= 0
            or not isfinite(float(price_risk))
            or price_risk == 0
        ):
            return 0

        if instrument is None:
            size = risk_amount / price_risk

            return round(size, 4)

        if not isinstance(instrument, InstrumentSpec):
            raise TypeError(
                "instrument must be an InstrumentSpec instance"
            )

        resolved_side = side

        if resolved_side is None:
            resolved_side = (
                "BUY"
                if float(stop_loss) < float(entry_price)
                else "SELL"
            )

        cash_risk_per_quantity = (
            instrument.planned_loss_per_quantity(
                entry_reference=entry_price,
                stop_reference=stop_loss,
                side=resolved_side
            )
        )

        if cash_risk_per_quantity <= 0:
            return 0

        size = risk_amount / cash_risk_per_quantity

        return instrument.normalize_quantity(size)
