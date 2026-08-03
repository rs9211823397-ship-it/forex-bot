"""Route validated trade plans to paper or MT5 demo execution.

The router keeps strategy code independent from the execution venue. PAPER is
always the default. MT5_LIVE is deliberately rejected until a separate live
release gate exists.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from config.settings import (
    EXECUTION_MODE,
    MT5_FIXED_LOT,
    MT5_MAX_OPEN_POSITIONS,
    MT5_SYMBOL_MAP,
    MT5_TERMINAL_PATH,
)
from execution.mt5_executor import (
    AccountSnapshot,
    ClosedPositionResult,
    ExecutionConfig,
    ExecutionError,
    MT5Executor,
)
from execution.position_manager import PositionManager


VALID_MODES = {"PAPER", "MT5_DEMO", "MT5_LIVE"}


class ExecutionRouter:
    def __init__(
        self,
        paper_trader: Any,
        mode: str = EXECUTION_MODE,
        mt5_executor: Optional[MT5Executor] = None,
        position_manager: Optional[PositionManager] = None,
    ) -> None:
        self.paper_trader = paper_trader
        self.mode = mode.upper().strip()
        if self.mode not in VALID_MODES:
            raise ValueError(f"Unsupported execution mode: {self.mode}")
        if self.mode == "MT5_LIVE":
            raise ExecutionError(
                "MT5_LIVE is locked. Use PAPER or MT5_DEMO until the live-release gate is implemented."
            )

        self.mt5_executor = mt5_executor
        if self.mode == "MT5_DEMO" and self.mt5_executor is None:
            self.mt5_executor = MT5Executor(
                ExecutionConfig(
                    terminal_path=MT5_TERMINAL_PATH,
                    max_open_positions=MT5_MAX_OPEN_POSITIONS,
                )
            )
        self.position_manager = position_manager
        if self.mode == "MT5_DEMO" and self.position_manager is None:
            assert self.mt5_executor is not None
            self.position_manager = PositionManager(self.mt5_executor)

    def start(self) -> list[Any]:
        """Connect MT5 demo and recover broker-held AAQTS positions."""
        if self.mode != "MT5_DEMO":
            return []
        assert self.mt5_executor is not None
        assert self.position_manager is not None
        self.mt5_executor.connect()
        return self.position_manager.recover_positions(reset_registry=True)

    def execute(
        self,
        source_symbol: str,
        signal: str,
        risk_plan: dict[str, float],
        paper_position_size: float,
    ) -> Any:
        """Execute one already risk-approved trade plan."""
        if not risk_plan:
            raise ValueError("risk_plan is required")
        required = {"entry", "stop_loss", "take_profit"}
        missing = required.difference(risk_plan)
        if missing:
            raise ValueError(f"risk_plan is missing: {', '.join(sorted(missing))}")

        side = signal.upper().strip()
        if side not in {"BUY", "SELL"}:
            raise ValueError("Only BUY or SELL signals can be executed")

        if self.mode == "PAPER":
            return self.paper_trader.open_trade(
                source_symbol,
                side,
                risk_plan["entry"],
                risk_plan["stop_loss"],
                risk_plan["take_profit"],
                paper_position_size,
            )

        assert self.mt5_executor is not None
        mt5_symbol = MT5_SYMBOL_MAP.get(source_symbol)
        if not mt5_symbol:
            raise ExecutionError(f"No MT5 symbol mapping configured for {source_symbol}")
        result = self.mt5_executor.place_market_order(
            symbol=mt5_symbol,
            side=side,
            volume=MT5_FIXED_LOT,
            stop_loss=risk_plan["stop_loss"],
            take_profit=risk_plan["take_profit"],
            comment=f"AAQTS {source_symbol}",
        )
        if self.position_manager is not None:
            self.position_manager.register_execution_result(result)
        return result

    def manage_positions(
        self,
        atr_by_source_symbol: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """Run one MT5 lifecycle cycle; paper exits are managed by PaperTrader."""
        if self.mode != "MT5_DEMO" or self.position_manager is None:
            return {
                "managed": False,
                "reason": "paper_mode_uses_price_checks",
                "reports": [],
                "errors": [],
            }
        atr_by_source_symbol = atr_by_source_symbol or {}
        broker_atr = {
            MT5_SYMBOL_MAP[source]: float(atr)
            for source, atr in atr_by_source_symbol.items()
            if source in MT5_SYMBOL_MAP
        }
        return self.position_manager.manage_positions(
            broker_atr,
            force_sync=False,
        )

    def pause(self) -> None:
        if self.mt5_executor is not None:
            self.mt5_executor.pause()

    def resume(self) -> None:
        if self.mt5_executor is not None:
            self.mt5_executor.resume()

    def emergency_stop(self) -> list[Any]:
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            return []
        return self.mt5_executor.emergency_stop()

    def positions(self) -> list[Any]:
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            return list(getattr(self.paper_trader, "open_trades", []))
        return self.mt5_executor.positions(managed_only=True)

    def account_snapshot(self) -> AccountSnapshot:
        """Return the account state belonging to the active execution venue."""
        if self.mode == "PAPER":
            return AccountSnapshot(
                balance=float(self.paper_trader.balance),
                equity=float(self.paper_trader.equity),
            )
        assert self.mt5_executor is not None
        return self.mt5_executor.account_snapshot()

    def closed_position_results(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[ClosedPositionResult]:
        """Return broker realized exits; paper history remains locally owned."""
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            return []
        return self.mt5_executor.closed_position_results(start_time, end_time)

    def position_side(self, position: Any) -> str:
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            return str(position["signal"]).upper()
        return self.mt5_executor.position_side(position)

    def remaining_loss_at_stop(self, position: Any) -> float:
        if self.mode != "MT5_DEMO" or self.mt5_executor is None:
            raise ExecutionError("Broker stop-risk calculation requires MT5_DEMO")
        return self.mt5_executor.remaining_loss_at_stop(position)

    def shutdown(self) -> None:
        """Disconnect only. Broker-side positions remain protected by SL/TP."""
        if self.mt5_executor is not None:
            self.mt5_executor.shutdown()
