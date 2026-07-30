from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Optional

from config.settings import RISK_PERCENT


@dataclass(frozen=True)
class TradeLevels:
    entry: float
    stop_loss: float
    take_profit: float
    stop_distance: float
    reward_distance: float
    risk_reward: float
    atr: float
    stop_atr_multiplier: float
    target_atr_multiplier: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    signal: str
    lot_size: float
    risk_amount: float
    estimated_reward: float
    risk_reward: float
    risk_percent: float
    entry: float
    stop_loss: float
    take_profit: float
    stop_distance: float
    risk_multiplier: float
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)

        result["reasons"] = list(self.reasons)
        result["warnings"] = list(self.warnings)

        return result


class RiskManager:
    """
    Central risk-control module for AAQTS.

    Main responsibilities:

    - Calculate ATR-based stop-loss and take-profit levels
    - Calculate broker-compatible position size
    - Apply market-regime risk multipliers
    - Validate spread and risk-reward ratio
    - Enforce account and daily protection limits
    - Return detailed trade approval or rejection reports

    Notes
    -----
    For accurate forex lot sizing, provide either:

    1. tick_size and tick_value, or
    2. pip_size and pip_value_per_lot

    The old fallback calculation is retained only for backward compatibility.
    """

    VALID_SIGNALS = {"BUY", "SELL", "HOLD"}

    def __init__(
        self,
        risk_percent: float = RISK_PERCENT,
        reward_ratio: float = 2.0,
        *,
        stop_atr_multiplier: float = 1.5,
        minimum_risk_reward: float = 1.5,
        maximum_risk_percent: float = 2.0,
        maximum_daily_loss_percent: float = 5.0,
        maximum_open_trades: int = 5,
        maximum_consecutive_losses: int = 3,
        maximum_spread_points: Optional[float] = None,
        minimum_stop_distance: float = 0.0,
        minimum_lot: float = 0.01,
        maximum_lot: float = 100.0,
        lot_step: float = 0.01,
    ) -> None:

        self.risk_percent = self._positive_float(
            risk_percent,
            "risk_percent",
        )

        self.reward_ratio = self._positive_float(
            reward_ratio,
            "reward_ratio",
        )

        self.stop_atr_multiplier = self._positive_float(
            stop_atr_multiplier,
            "stop_atr_multiplier",
        )

        self.minimum_risk_reward = self._positive_float(
            minimum_risk_reward,
            "minimum_risk_reward",
        )

        self.maximum_risk_percent = self._positive_float(
            maximum_risk_percent,
            "maximum_risk_percent",
        )

        self.maximum_daily_loss_percent = self._positive_float(
            maximum_daily_loss_percent,
            "maximum_daily_loss_percent",
        )

        self.maximum_open_trades = max(
            1,
            int(maximum_open_trades),
        )

        self.maximum_consecutive_losses = max(
            1,
            int(maximum_consecutive_losses),
        )

        self.maximum_spread_points = (
            None
            if maximum_spread_points is None
            else self._positive_float(
                maximum_spread_points,
                "maximum_spread_points",
            )
        )

        self.minimum_stop_distance = max(
            0.0,
            float(minimum_stop_distance),
        )

        self.minimum_lot = self._positive_float(
            minimum_lot,
            "minimum_lot",
        )

        self.maximum_lot = self._positive_float(
            maximum_lot,
            "maximum_lot",
        )

        self.lot_step = self._positive_float(
            lot_step,
            "lot_step",
        )

        if self.risk_percent > self.maximum_risk_percent:
            raise ValueError(
                "risk_percent cannot exceed maximum_risk_percent"
            )

        if self.minimum_lot > self.maximum_lot:
            raise ValueError(
                "minimum_lot cannot exceed maximum_lot"
            )

    ###########################################################################
    # TRADE LEVELS
    ###########################################################################

    def calculate_trade_levels(
        self,
        signal: str,
        entry_price: float,
        atr: float,
        *,
        stop_atr_multiplier: Optional[float] = None,
        reward_ratio: Optional[float] = None,
        price_digits: int = 5,
    ) -> Optional[dict[str, Any]]:
        """
        Calculate ATR-based stop-loss and take-profit levels.

        Backward compatible with the original method.
        """

        signal = self._normalize_signal(signal)

        if signal == "HOLD":
            return None

        entry_price = self._positive_float(
            entry_price,
            "entry_price",
        )

        atr = self._positive_float(
            atr,
            "atr",
        )

        stop_multiplier = (
            self.stop_atr_multiplier
            if stop_atr_multiplier is None
            else self._positive_float(
                stop_atr_multiplier,
                "stop_atr_multiplier",
            )
        )

        target_ratio = (
            self.reward_ratio
            if reward_ratio is None
            else self._positive_float(
                reward_ratio,
                "reward_ratio",
            )
        )

        stop_distance = atr * stop_multiplier
        reward_distance = stop_distance * target_ratio

        if signal == "BUY":
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + reward_distance

        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - reward_distance

        if stop_loss <= 0 or take_profit <= 0:
            raise ValueError(
                "Calculated trade levels must remain above zero"
            )

        actual_risk = abs(
            entry_price - stop_loss
        )

        actual_reward = abs(
            take_profit - entry_price
        )

        risk_reward = (
            actual_reward / actual_risk
            if actual_risk > 0
            else 0.0
        )

        levels = TradeLevels(
            entry=round(
                entry_price,
                price_digits,
            ),
            stop_loss=round(
                stop_loss,
                price_digits,
            ),
            take_profit=round(
                take_profit,
                price_digits,
            ),
            stop_distance=round(
                actual_risk,
                price_digits,
            ),
            reward_distance=round(
                actual_reward,
                price_digits,
            ),
            risk_reward=round(
                risk_reward,
                2,
            ),
            atr=round(
                atr,
                price_digits,
            ),
            stop_atr_multiplier=round(
                stop_multiplier,
                2,
            ),
            target_atr_multiplier=round(
                stop_multiplier * target_ratio,
                2,
            ),
        )

        return levels.to_dict()

    ###########################################################################
    # POSITION SIZING
    ###########################################################################

    def position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss: float,
        *,
        risk_percent: Optional[float] = None,
        risk_multiplier: float = 1.0,
        tick_size: Optional[float] = None,
        tick_value: Optional[float] = None,
        pip_size: Optional[float] = None,
        pip_value_per_lot: Optional[float] = None,
        minimum_lot: Optional[float] = None,
        maximum_lot: Optional[float] = None,
        lot_step: Optional[float] = None,
    ) -> float:
        """
        Calculate broker-compatible lot size.

        Preferred calculation:

            loss_per_lot =
                stop_distance / tick_size * tick_value

        Alternative calculation:

            loss_per_lot =
                stop_distance / pip_size * pip_value_per_lot

        A legacy fallback is retained when symbol specifications are not
        supplied, but it should not be used for live forex execution.
        """

        account_balance = self._positive_float(
            account_balance,
            "account_balance",
        )

        entry_price = self._positive_float(
            entry_price,
            "entry_price",
        )

        stop_loss = self._positive_float(
            stop_loss,
            "stop_loss",
        )

        risk_percentage = (
            self.risk_percent
            if risk_percent is None
            else self._positive_float(
                risk_percent,
                "risk_percent",
            )
        )

        if risk_percentage > self.maximum_risk_percent:
            return 0.0

        risk_multiplier = self._bounded_float(
            risk_multiplier,
            minimum=0.0,
            maximum=1.0,
            name="risk_multiplier",
        )

        if risk_multiplier <= 0:
            return 0.0

        risk_amount = (
            account_balance
            * risk_percentage
            / 100.0
            * risk_multiplier
        )

        stop_distance = abs(
            entry_price - stop_loss
        )

        if stop_distance <= 0:
            return 0.0

        if (
            self.minimum_stop_distance > 0
            and stop_distance < self.minimum_stop_distance
        ):
            return 0.0

        loss_per_lot: float

        if (
            tick_size is not None
            and tick_value is not None
        ):
            tick_size = self._positive_float(
                tick_size,
                "tick_size",
            )

            tick_value = self._positive_float(
                tick_value,
                "tick_value",
            )

            number_of_ticks = (
                stop_distance / tick_size
            )

            loss_per_lot = (
                number_of_ticks * tick_value
            )

        elif (
            pip_size is not None
            and pip_value_per_lot is not None
        ):
            pip_size = self._positive_float(
                pip_size,
                "pip_size",
            )

            pip_value_per_lot = self._positive_float(
                pip_value_per_lot,
                "pip_value_per_lot",
            )

            number_of_pips = (
                stop_distance / pip_size
            )

            loss_per_lot = (
                number_of_pips
                * pip_value_per_lot
            )

        else:
            # Backward-compatible fallback.
            # This value is not guaranteed to represent MT5 lots.
            loss_per_lot = stop_distance

        if loss_per_lot <= 0:
            return 0.0

        raw_lot_size = (
            risk_amount / loss_per_lot
        )

        min_lot = (
            self.minimum_lot
            if minimum_lot is None
            else self._positive_float(
                minimum_lot,
                "minimum_lot",
            )
        )

        max_lot = (
            self.maximum_lot
            if maximum_lot is None
            else self._positive_float(
                maximum_lot,
                "maximum_lot",
            )
        )

        step = (
            self.lot_step
            if lot_step is None
            else self._positive_float(
                lot_step,
                "lot_step",
            )
        )

        if raw_lot_size < min_lot:
            return 0.0

        raw_lot_size = min(
            raw_lot_size,
            max_lot,
        )

        normalized_lot = self._floor_to_step(
            raw_lot_size,
            step,
        )

        if normalized_lot < min_lot:
            return 0.0

        return round(
            normalized_lot,
            self._step_precision(step),
        )

    ###########################################################################
    # COMPLETE TRADE VALIDATION
    ###########################################################################

    def evaluate_trade(
        self,
        *,
        signal: str,
        account_balance: float,
        entry_price: float,
        atr: float,
        risk_multiplier: float = 1.0,
        account_equity: Optional[float] = None,
        daily_profit_loss: float = 0.0,
        open_trades: int = 0,
        consecutive_losses: int = 0,
        spread_points: Optional[float] = None,
        tick_size: Optional[float] = None,
        tick_value: Optional[float] = None,
        pip_size: Optional[float] = None,
        pip_value_per_lot: Optional[float] = None,
        minimum_lot: Optional[float] = None,
        maximum_lot: Optional[float] = None,
        lot_step: Optional[float] = None,
        stop_atr_multiplier: Optional[float] = None,
        reward_ratio: Optional[float] = None,
        price_digits: int = 5,
    ) -> dict[str, Any]:
        """
        Perform complete pre-trade risk validation.
        """

        reasons: list[str] = []
        warnings: list[str] = []

        try:
            signal = self._normalize_signal(
                signal
            )

        except ValueError as exc:
            return self._rejected_decision(
                signal=str(signal),
                reason=str(exc),
            )

        if signal == "HOLD":
            return self._rejected_decision(
                signal=signal,
                reason="HOLD signal does not request a trade",
            )

        try:
            account_balance = self._positive_float(
                account_balance,
                "account_balance",
            )

            entry_price = self._positive_float(
                entry_price,
                "entry_price",
            )

            atr = self._positive_float(
                atr,
                "atr",
            )

            risk_multiplier = self._bounded_float(
                risk_multiplier,
                minimum=0.0,
                maximum=1.0,
                name="risk_multiplier",
            )

        except ValueError as exc:
            return self._rejected_decision(
                signal=signal,
                reason=str(exc),
            )

        if risk_multiplier <= 0:
            return self._rejected_decision(
                signal=signal,
                reason="Risk multiplier blocks trading",
            )

        #######################################################################
        # ACCOUNT PROTECTION
        #######################################################################

        effective_equity = (
            account_balance
            if account_equity is None
            else float(account_equity)
        )

        if effective_equity <= 0:
            return self._rejected_decision(
                signal=signal,
                reason="Account equity must be greater than zero",
            )

        drawdown_percent = max(
            0.0,
            (
                account_balance
                - effective_equity
            )
            / account_balance
            * 100.0,
        )

        if drawdown_percent >= self.maximum_daily_loss_percent:
            return self._rejected_decision(
                signal=signal,
                reason=(
                    "Account drawdown reached the configured "
                    "daily protection limit"
                ),
            )

        daily_loss_limit = (
            account_balance
            * self.maximum_daily_loss_percent
            / 100.0
        )

        if daily_profit_loss <= -daily_loss_limit:
            return self._rejected_decision(
                signal=signal,
                reason="Maximum daily loss limit reached",
            )

        if open_trades >= self.maximum_open_trades:
            return self._rejected_decision(
                signal=signal,
                reason="Maximum number of open trades reached",
            )

        if (
            consecutive_losses
            >= self.maximum_consecutive_losses
        ):
            return self._rejected_decision(
                signal=signal,
                reason="Maximum consecutive-loss limit reached",
            )

        #######################################################################
        # SPREAD VALIDATION
        #######################################################################

        if (
            spread_points is not None
            and self.maximum_spread_points is not None
        ):
            spread_points = max(
                0.0,
                float(spread_points),
            )

            if (
                spread_points
                > self.maximum_spread_points
            ):
                return self._rejected_decision(
                    signal=signal,
                    reason=(
                        f"Spread is too high: {spread_points:.1f} points"
                    ),
                )

            if (
                spread_points
                >= self.maximum_spread_points * 0.80
            ):
                warnings.append(
                    "Spread is close to the configured maximum"
                )

        #######################################################################
        # LEVEL CALCULATION
        #######################################################################

        try:
            levels = self.calculate_trade_levels(
                signal=signal,
                entry_price=entry_price,
                atr=atr,
                stop_atr_multiplier=stop_atr_multiplier,
                reward_ratio=reward_ratio,
                price_digits=price_digits,
            )

        except ValueError as exc:
            return self._rejected_decision(
                signal=signal,
                reason=str(exc),
            )

        if levels is None:
            return self._rejected_decision(
                signal=signal,
                reason="Unable to calculate trade levels",
            )

        stop_distance = float(
            levels["stop_distance"]
        )

        risk_reward = float(
            levels["risk_reward"]
        )

        if (
            self.minimum_stop_distance > 0
            and stop_distance < self.minimum_stop_distance
        ):
            return self._rejected_decision(
                signal=signal,
                reason="Stop-loss distance is below the allowed minimum",
            )

        if risk_reward < self.minimum_risk_reward:
            return self._rejected_decision(
                signal=signal,
                reason=(
                    f"Risk-reward ratio {risk_reward:.2f} is below "
                    f"minimum {self.minimum_risk_reward:.2f}"
                ),
            )

        #######################################################################
        # LOT SIZE
        #######################################################################

        lot_size = self.position_size(
            account_balance=account_balance,
            entry_price=float(
                levels["entry"]
            ),
            stop_loss=float(
                levels["stop_loss"]
            ),
            risk_multiplier=risk_multiplier,
            tick_size=tick_size,
            tick_value=tick_value,
            pip_size=pip_size,
            pip_value_per_lot=pip_value_per_lot,
            minimum_lot=minimum_lot,
            maximum_lot=maximum_lot,
            lot_step=lot_step,
        )

        if lot_size <= 0:
            return self._rejected_decision(
                signal=signal,
                reason=(
                    "Calculated lot size is below the broker minimum "
                    "or symbol specifications are invalid"
                ),
            )

        effective_risk_percent = (
            self.risk_percent
            * risk_multiplier
        )

        risk_amount = (
            account_balance
            * effective_risk_percent
            / 100.0
        )

        estimated_reward = (
            risk_amount
            * risk_reward
        )

        reasons.extend(
            [
                "Account protection checks passed",
                "Risk-reward requirement passed",
                "Position size calculated successfully",
                f"{signal} trade approved",
            ]
        )

        if tick_size is None or tick_value is None:
            if (
                pip_size is None
                or pip_value_per_lot is None
            ):
                warnings.append(
                    "Broker tick or pip specifications were not supplied; "
                    "lot-size fallback may not represent real MT5 volume"
                )

        decision = RiskDecision(
            approved=True,
            signal=signal,
            lot_size=lot_size,
            risk_amount=round(
                risk_amount,
                2,
            ),
            estimated_reward=round(
                estimated_reward,
                2,
            ),
            risk_reward=round(
                risk_reward,
                2,
            ),
            risk_percent=round(
                effective_risk_percent,
                3,
            ),
            entry=float(
                levels["entry"]
            ),
            stop_loss=float(
                levels["stop_loss"]
            ),
            take_profit=float(
                levels["take_profit"]
            ),
            stop_distance=stop_distance,
            risk_multiplier=round(
                risk_multiplier,
                2,
            ),
            reasons=tuple(
                self._unique(reasons)
            ),
            warnings=tuple(
                self._unique(warnings)
            ),
        )

        result = decision.to_dict()

        result["trade_levels"] = levels
        result["daily_loss_limit"] = round(
            daily_loss_limit,
            2,
        )
        result["daily_profit_loss"] = round(
            float(daily_profit_loss),
            2,
        )
        result["open_trades"] = int(
            open_trades
        )
        result["consecutive_losses"] = int(
            consecutive_losses
        )

        return result

    ###########################################################################
    # HELPERS
    ###########################################################################

    @classmethod
    def _normalize_signal(
        cls,
        signal: str,
    ) -> str:

        normalized = str(
            signal
        ).upper().strip()

        if normalized not in cls.VALID_SIGNALS:
            raise ValueError(
                f"Unsupported signal: {signal}"
            )

        return normalized

    @staticmethod
    def _positive_float(
        value: Any,
        name: str,
    ) -> float:

        try:
            result = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                f"{name} must be numeric"
            ) from exc

        if (
            not math.isfinite(result)
            or result <= 0
        ):
            raise ValueError(
                f"{name} must be greater than zero"
            )

        return result

    @staticmethod
    def _bounded_float(
        value: Any,
        *,
        minimum: float,
        maximum: float,
        name: str,
    ) -> float:

        try:
            result = float(
                value
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                f"{name} must be numeric"
            ) from exc

        if not math.isfinite(result):
            raise ValueError(
                f"{name} must be finite"
            )

        if not minimum <= result <= maximum:
            raise ValueError(
                f"{name} must be between {minimum} and {maximum}"
            )

        return result

    @staticmethod
    def _floor_to_step(
        value: float,
        step: float,
    ) -> float:

        return (
            math.floor(
                value / step + 1e-12
            )
            * step
        )

    @staticmethod
    def _step_precision(
        step: float,
    ) -> int:

        text = (
            f"{step:.10f}"
            .rstrip("0")
            .rstrip(".")
        )

        if "." not in text:
            return 0

        return len(
            text.split(".")[1]
        )

    @staticmethod
    def _unique(
        values: list[str],
    ) -> list[str]:

        result: list[str] = []

        for value in values:
            normalized = str(
                value
            ).strip()

            if (
                normalized
                and normalized not in result
            ):
                result.append(
                    normalized
                )

        return result

    @staticmethod
    def _rejected_decision(
        *,
        signal: str,
        reason: str,
    ) -> dict[str, Any]:

        return RiskDecision(
            approved=False,
            signal=str(signal).upper().strip(),
            lot_size=0.0,
            risk_amount=0.0,
            estimated_reward=0.0,
            risk_reward=0.0,
            risk_percent=0.0,
            entry=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            stop_distance=0.0,
            risk_multiplier=0.0,
            reasons=(reason,),
            warnings=(),
        ).to_dict()