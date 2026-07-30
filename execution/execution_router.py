"""Route validated trade plans to paper or MT5 demo execution.

The router keeps strategy code independent from the execution venue. PAPER is
always the default. MT5_LIVE is deliberately rejected until a separate live
release gate exists.
"""

from __future__ import annotations

from typing import Any, Optional

from config.settings import (
    EXECUTION_MODE,
    MT5_FIXED_LOT,
    MT5_MAX_OPEN_POSITIONS,
    MT5_SYMBOL_MAP,
    MT5_TERMINAL_PATH,
)
from execution.mt5_executor import ExecutionConfig, ExecutionError, MT5Executor


VALID_MODES = {"PAPER", "MT5_DEMO", "MT5_LIVE"}


class ExecutionRouter:
    def __init__(
        self,
        paper_trader: Any,
        mode: str = EXECUTION_MODE,
        mt5_executor: Optional[MT5Executor] = None,
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

    def start(self) -> list[Any]:
        """Connect MT5 demo and recover broker-held AAQTS positions."""
        if self.mode != "MT5_DEMO":
            return []
        assert self.mt5_executor is not None
        self.mt5_executor.connect()
        return self.mt5_executor.recover_positions()

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
        return self.mt5_executor.place_market_order(
            symbol=mt5_symbol,
            side=side,
            volume=MT5_FIXED_LOT,
            stop_loss=risk_plan["stop_loss"],
            take_profit=risk_plan["take_profit"],
            comment=f"AAQTS {source_symbol}",
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

    def shutdown(self) -> None:
        """Disconnect only. Broker-side positions remain protected by SL/TP."""
        if self.mt5_executor is not None:
            self.mt5_executor.shutdown()
