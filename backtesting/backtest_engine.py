"""Deterministic next-bar backtest execution and cash accounting."""

from math import isfinite

from risk.instrument import InstrumentSpec
from risk.risk_manager import RiskManager


class BacktestEngine:
    """
    Execute close-confirmed signals no earlier than the next candle open.

    Existing ``BacktestEngine(data, strategy)`` callers remain supported.
    Optional keyword arguments configure accounting without changing the
    strategy callback contract.
    """

    REQUIRED_COLUMNS = {
        "open",
        "high",
        "low",
        "close",
        "ATR",
        "ADX"
    }

    def __init__(
        self,
        data,
        strategy,
        *,
        initial_equity=1000.0,
        risk_percent=1.0,
        instrument=None,
        same_bar_policy="STOP_FIRST",
        force_close=False
    ):
        self.data = data
        self.strategy = strategy
        self.initial_equity = float(initial_equity)
        self.risk_percent = float(risk_percent)
        self.instrument = (
            instrument or InstrumentSpec.generic()
        )
        self.same_bar_policy = same_bar_policy
        self.force_close = bool(force_close)
        self.risk_manager = RiskManager(
            risk_percent=self.risk_percent
        )
        self.trades = []
        self.orders = []
        self.balance = self.initial_equity
        self.equity = self.initial_equity
        self.equity_history = [self.initial_equity]
        self.open_position = None
        self.pending_order = None

        if (
            not isfinite(self.initial_equity)
            or self.initial_equity <= 0
        ):
            raise ValueError(
                "initial_equity must be finite and greater than zero"
            )

        if (
            not isfinite(self.risk_percent)
            or self.risk_percent <= 0
        ):
            raise ValueError(
                "risk_percent must be finite and greater than zero"
            )

        if not isinstance(self.instrument, InstrumentSpec):
            raise TypeError(
                "instrument must be an InstrumentSpec instance"
            )

        if self.same_bar_policy != "STOP_FIRST":
            raise ValueError(
                "Only conservative STOP_FIRST same-bar policy is supported"
            )

    def _reset(self):
        self.trades = []
        self.orders = []
        self.balance = self.initial_equity
        self.equity = self.initial_equity
        self.equity_history = [self.initial_equity]
        self.open_position = None
        self.pending_order = None

    def _validate_data(self):
        if self.data.empty:
            return

        missing = self.REQUIRED_COLUMNS.difference(
            self.data.columns
        )

        if missing:
            raise ValueError(
                "Backtest data missing columns: "
                + ", ".join(sorted(missing))
            )

        for _, row in self.data.iterrows():
            values = [
                float(row[column])
                for column in self.REQUIRED_COLUMNS
            ]

            if not all(isfinite(value) for value in values):
                raise ValueError(
                    "Backtest OHLC and indicator values must be finite"
                )

            if (
                float(row["high"])
                < max(float(row["open"]), float(row["close"]))
                or float(row["low"])
                > min(float(row["open"]), float(row["close"]))
                or float(row["high"]) < float(row["low"])
            ):
                raise ValueError("Invalid backtest OHLC geometry")

            if float(row["ATR"]) <= 0:
                raise ValueError(
                    "Backtest ATR must be greater than zero"
                )

        if "close_time" in self.data.columns:
            timestamps = self.data["close_time"]

            if timestamps.isna().any():
                raise ValueError(
                    "Backtest timestamps cannot contain missing values"
                )

            if timestamps.duplicated().any():
                raise ValueError(
                    "Backtest timestamps must be unique"
                )

            if not timestamps.is_monotonic_increasing:
                raise ValueError(
                    "Backtest timestamps must be monotonic increasing"
                )
        else:
            if self.data.index.hasnans:
                raise ValueError(
                    "Backtest timestamps cannot contain missing values"
                )

            if self.data.index.has_duplicates:
                raise ValueError(
                    "Backtest timestamps must be unique"
                )

            if not self.data.index.is_monotonic_increasing:
                raise ValueError(
                    "Backtest timestamps must be monotonic increasing"
                )

    def _decision_time(self, index, row):
        if "close_time" in row.index:
            return row["close_time"]

        return index

    def _fill_time(self, index, row):
        if "open_time" in row.index:
            return row["open_time"]

        return index

    def _signal_value(self, raw_signal):
        if isinstance(raw_signal, dict):
            value = raw_signal.get("signal", "HOLD")
        elif hasattr(raw_signal, "signal"):
            value = raw_signal.signal
        else:
            value = raw_signal

        normalized = str(value).upper()

        if normalized not in {"BUY", "SELL", "HOLD"}:
            raise ValueError(
                "Strategy signal must be BUY, SELL, or HOLD"
            )

        return normalized

    def _multipliers(self, adx):
        if adx >= 40:
            return 2.0, 3.5

        if adx >= 30:
            return 1.8, 3.0

        return 1.5, 2.5

    def _create_order(self, position, index, row, side):
        decision_time = self._decision_time(index, row)
        next_position = position + 1
        eligible_fill_time = None

        if next_position < len(self.data):
            next_index = self.data.index[next_position]
            next_row = self.data.iloc[next_position]
            eligible_fill_time = self._fill_time(
                next_index,
                next_row
            )

        order = {
            "id": len(self.orders) + 1,
            "side": side,
            "decision_time": decision_time,
            "created_time": decision_time,
            "eligible_fill_time": eligible_fill_time,
            "fill_time": None,
            "decision_price": float(row["close"]),
            "atr": float(row["ATR"]),
            "adx": float(row["ADX"]),
            "status": (
                "PENDING"
                if eligible_fill_time is not None
                else "UNFILLED_NO_NEXT_CANDLE"
            ),
            "eligible_position": (
                next_position
                if eligible_fill_time is not None
                else None
            )
        }
        self.orders.append(order)

        if eligible_fill_time is not None:
            self.pending_order = order

    def _fill_pending_order(self, position, index, row):
        order = self.pending_order

        if (
            order is None
            or order["eligible_position"] != position
        ):
            return

        side = order["side"]
        entry_reference = float(row["open"])
        entry_price = self.instrument.entry_fill_price(
            entry_reference,
            side
        )
        stop_multiplier, target_multiplier = self._multipliers(
            order["adx"]
        )

        if side == "BUY":
            stop_loss = (
                entry_reference
                - stop_multiplier * order["atr"]
            )
            take_profit = (
                entry_reference
                + target_multiplier * order["atr"]
            )
            position_side = "LONG"
        else:
            stop_loss = (
                entry_reference
                + stop_multiplier * order["atr"]
            )
            take_profit = (
                entry_reference
                - target_multiplier * order["atr"]
            )
            position_side = "SHORT"

        quantity = self.risk_manager.position_size(
            self.equity,
            entry_reference,
            stop_loss,
            instrument=self.instrument,
            side=side
        )

        if quantity <= 0:
            order["status"] = "REJECTED_ZERO_QUANTITY"
            self.pending_order = None
            return

        fill_time = self._fill_time(index, row)
        price_risk = self.instrument.cash_value(
            entry_reference - stop_loss,
            quantity
        )
        initial_risk = (
            self.instrument.planned_loss_per_quantity(
                entry_reference,
                stop_loss,
                side
            )
            * quantity
        )
        risk_percent = (
            initial_risk / self.equity * 100.0
            if self.equity != 0
            else 0.0
        )
        entry_trade = {
            "type": "ENTRY",
            "side": side,
            "position_side": position_side,
            "price": entry_price,
            "entry_reference_price": entry_reference,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "time": fill_time,
            "decision_time": order["decision_time"],
            "created_time": order["created_time"],
            "eligible_fill_time": order["eligible_fill_time"],
            "fill_time": fill_time,
            "quantity": quantity,
            "price_risk": price_risk,
            "initial_risk": initial_risk,
            "risk_percent": risk_percent,
            "status": "OPEN"
        }
        self.trades.append(entry_trade)
        self.open_position = {
            "side": side,
            "position_side": position_side,
            "entry_price": entry_price,
            "entry_reference_price": entry_reference,
            "entry_time": fill_time,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "quantity": quantity,
            "price_risk": price_risk,
            "initial_risk": initial_risk,
            "risk_percent": risk_percent,
            "starting_equity": self.equity,
            "entry_trade": entry_trade
        }
        order["status"] = "FILLED"
        order["fill_time"] = fill_time
        order["fill_price"] = entry_price
        order["quantity"] = quantity
        self.pending_order = None

    def _exit_candidate(self, row):
        position = self.open_position

        if position is None:
            return None

        side = position["side"]
        stop_loss = position["stop_loss"]
        take_profit = position["take_profit"]
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])

        if side == "BUY":
            if open_price <= stop_loss:
                return (
                    open_price,
                    "STOP LOSS",
                    "STOP_LOSS_GAP"
                )

            if open_price >= take_profit:
                return (
                    take_profit,
                    "TAKE PROFIT",
                    "TAKE_PROFIT_GAP_CONSERVATIVE"
                )

            stop_hit = low <= stop_loss
            target_hit = high >= take_profit
        else:
            if open_price >= stop_loss:
                return (
                    open_price,
                    "STOP LOSS",
                    "STOP_LOSS_GAP"
                )

            if open_price <= take_profit:
                return (
                    take_profit,
                    "TAKE PROFIT",
                    "TAKE_PROFIT_GAP_CONSERVATIVE"
                )

            stop_hit = high >= stop_loss
            target_hit = low <= take_profit

        if stop_hit and target_hit:
            return (
                stop_loss,
                "STOP LOSS",
                "SAME_BAR_STOP_FIRST_CONSERVATIVE"
            )

        if stop_hit:
            return (
                stop_loss,
                "STOP LOSS",
                "STOP_LOSS_INTRABAR"
            )

        if target_hit:
            return (
                take_profit,
                "TAKE PROFIT",
                "TAKE_PROFIT_INTRABAR"
            )

        return None

    def _close_position(
        self,
        index,
        row,
        reference_price,
        result,
        exit_reason
    ):
        position = self.open_position
        side = position["side"]
        quantity = position["quantity"]
        if "GAP" in exit_reason:
            exit_time = self._fill_time(index, row)
        else:
            exit_time = self._decision_time(index, row)
        exit_price = self.instrument.exit_fill_price(
            reference_price,
            side
        )

        if side == "BUY":
            reference_price_profit = (
                reference_price
                - position["entry_reference_price"]
            )
            fill_price_profit = (
                exit_price - position["entry_price"]
            )
        else:
            reference_price_profit = (
                position["entry_reference_price"]
                - reference_price
            )
            fill_price_profit = (
                position["entry_price"] - exit_price
            )

        reference_profit = (
            reference_price_profit
            * quantity
            * self.instrument.contract_multiplier
        )
        gross_profit = (
            fill_price_profit
            * quantity
            * self.instrument.contract_multiplier
        )
        spread_cost = self.instrument.spread_cost(quantity)
        slippage_cost = self.instrument.slippage_cost(quantity)
        execution_price_cost = (
            reference_profit - gross_profit
        )
        tick_rounding_cost = (
            execution_price_cost
            - spread_cost
            - slippage_cost
        )

        if abs(tick_rounding_cost) < 1e-12:
            tick_rounding_cost = 0.0

        commission = self.instrument.commission_cost(quantity)
        total_cost = (
            execution_price_cost
            + commission
        )
        net_profit = gross_profit - commission
        initial_risk = position["initial_risk"]
        r_multiple = (
            net_profit / initial_risk
            if initial_risk > 0
            else 0.0
        )

        self.balance += net_profit
        self.equity = self.balance
        position["entry_trade"]["status"] = "CLOSED"

        self.trades.append({
            "type": "EXIT",
            "side": position["position_side"],
            "entry_side": side,
            "entry_price": position["entry_price"],
            "entry_reference_price": (
                position["entry_reference_price"]
            ),
            "exit_price": exit_price,
            "exit_reference_price": reference_price,
            "profit": net_profit,
            "gross_profit": gross_profit,
            "reference_profit": reference_profit,
            "spread_cost": spread_cost,
            "slippage_cost": slippage_cost,
            "tick_rounding_cost": tick_rounding_cost,
            "commission": commission,
            "total_cost": total_cost,
            "result": result,
            "exit_reason": exit_reason,
            "entry_time": position["entry_time"],
            "exit_time": exit_time,
            "fill_time": exit_time,
            "quantity": quantity,
            "price_risk": position["price_risk"],
            "initial_risk": initial_risk,
            "risk_percent": position["risk_percent"],
            "r_multiple": r_multiple,
            "starting_equity": position["starting_equity"],
            "balance": self.balance,
            "equity": self.equity
        })
        self.open_position = None

    def _mark_equity(self, row):
        if self.open_position is None:
            self.equity = self.balance
            self.equity_history.append(self.equity)
            return

        reference_price = float(row["close"])
        position = self.open_position
        side = position["side"]
        quantity = position["quantity"]

        exit_price = self.instrument.exit_fill_price(
            reference_price,
            side
        )

        if side == "BUY":
            fill_price_profit = (
                exit_price - position["entry_price"]
            )
        else:
            fill_price_profit = (
                position["entry_price"] - exit_price
            )

        gross_profit = (
            fill_price_profit
            * quantity
            * self.instrument.contract_multiplier
        )
        unrealized_profit = (
            gross_profit
            - self.instrument.commission_cost(quantity)
        )
        self.equity = self.balance + unrealized_profit
        position["unrealized_profit"] = unrealized_profit
        position["marked_equity"] = self.equity
        self.equity_history.append(self.equity)

    def run(self):
        self._reset()
        self._validate_data()

        for position, (index, row) in enumerate(
            self.data.iterrows()
        ):
            self._fill_pending_order(
                position,
                index,
                row
            )
            exit_candidate = self._exit_candidate(row)

            if exit_candidate is not None:
                self._close_position(
                    index,
                    row,
                    *exit_candidate
                )

            if (
                self.open_position is None
                and self.pending_order is None
            ):
                raw_signal = self.strategy(position)
                signal = self._signal_value(raw_signal)

                if signal in {"BUY", "SELL"}:
                    self._create_order(
                        position,
                        index,
                        row,
                        signal
                    )

            self._mark_equity(row)

        if (
            self.force_close
            and self.open_position is not None
            and not self.data.empty
        ):
            last_position = len(self.data) - 1
            last_index = self.data.index[last_position]
            last_row = self.data.iloc[last_position]
            self._close_position(
                last_index,
                last_row,
                float(last_row["close"]),
                "FORCED EXIT",
                "END_OF_DATA_FORCE_CLOSE"
            )
            self.equity_history[-1] = self.equity

        return self.trades
