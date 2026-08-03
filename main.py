"""AAQTS application entry point.

PAPER is the default execution mode. MT5_DEMO requires an explicit environment
setting, and MT5_LIVE remains blocked by :class:`ExecutionRouter`.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from bot_controller import BotController
from bot_loop import BotLoop
from config.instruments import get_instrument_spec
from config.settings import (
    BOT_INTERVAL_SECONDS,
    EXECUTION_MODE,
    HIGHER_TIMEFRAME,
    MT5_MAX_OPEN_POSITIONS,
    RISK_PERCENT,
    TRADING_TIMEFRAME,
)
from data.market_data import MarketData
from data.timeframes import frame_decision_time
from execution.execution_router import ExecutionRouter
from execution.trade_manager import TradeManager
from indicators.technical import TechnicalIndicators
from logs.logger import TradeLogger
from paper.paper_trader import PaperTrader
from risk.portfolio import OpenRiskPosition
from risk.protection import (
    ClosedTradeOutcome,
    EquityPoint,
    PortfolioRiskManager,
    ProtectionConfig,
    RiskContext,
    TradeRiskRequest,
)
from risk.risk_manager import RiskManager
from runtime_state import write_runtime_state
from strategy.signal_engine import SignalEngine


logger = logging.getLogger(__name__)


class TradingApplication:
    """Compose market data, strategy, risk, and execution services."""

    def __init__(self) -> None:
        self.market = MarketData()
        self.indicators = TechnicalIndicators()
        self.signal_engine = SignalEngine.production(
            higher_timeframe=HIGHER_TIMEFRAME,
            lower_timeframe=TRADING_TIMEFRAME,
        )
        self.trade_manager = TradeManager()
        self.risk_manager = RiskManager()
        self.portfolio_risk = PortfolioRiskManager(
            ProtectionConfig(
                max_daily_loss_percent=2.0,
                max_weekly_loss_percent=5.0,
                max_equity_drawdown_percent=10.0,
                max_consecutive_losses=3,
                max_open_trades=MT5_MAX_OPEN_POSITIONS,
                max_portfolio_risk_percent=3.0,
            )
        )
        self.paper_trader = PaperTrader()
        self.execution = ExecutionRouter(self.paper_trader)
        self.trade_logger = TradeLogger()
        self.equity_history: list[EquityPoint] = []
        self.loop = BotLoop(interval=BOT_INTERVAL_SECONDS)
        self.controller = BotController.configured(
            bot_loop=self.loop,
            execution_router=self.execution,
            callback=self.run_cycle,
        )

    @staticmethod
    def _parse_time(value: object, fallback: datetime) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                return fallback
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _risk_context(self, decision_time: datetime) -> RiskContext:
        positions = []
        for trade in self.paper_trader.open_trades:
            try:
                instrument = get_instrument_spec(trade["symbol"])
                quantity = float(trade["position"])
                risk_amount = instrument.planned_loss_per_quantity(
                    entry_reference=trade["entry"],
                    stop_reference=trade["stop_loss"],
                    side=trade["signal"],
                ) * quantity
                positions.append(
                    OpenRiskPosition(
                        symbol=trade["symbol"],
                        direction=trade["signal"],
                        opened_at=self._parse_time(
                            trade.get("opened_at"), decision_time
                        ),
                        risk_amount=risk_amount,
                        quantity=quantity,
                        strategy="aaqts",
                    )
                )
            except (KeyError, TypeError, ValueError):
                logger.exception("Ignoring malformed open paper position")

        closed = []
        for trade in self.paper_trader.closed_trades:
            if "closed_at" not in trade:
                continue
            closed.append(
                ClosedTradeOutcome(
                    closed_at=self._parse_time(
                        trade["closed_at"], decision_time
                    ),
                    profit_loss=float(trade.get("pnl", 0.0)),
                )
            )

        return RiskContext(
            open_positions=tuple(positions),
            closed_trades=tuple(closed),
            equity_history=tuple(self.equity_history),
        )

    def _process_symbol(self, symbol, data, higher_tf) -> float:
        analyzed = self.indicators.add_indicators(data)
        signal = self.signal_engine.generate_analysis(
            analyzed, symbol, higher_tf
        )
        trade = self.trade_manager.calculate_trade(analyzed, signal)
        current_price = float(trade["current_price"])

        self.trade_logger.log_signal(
            symbol, signal["signal"], signal["confidence"]
        )
        self.paper_trader.check_trade(symbol, current_price)

        if signal["signal"] not in {"BUY", "SELL"}:
            return current_price

        risk_plan = self.risk_manager.calculate_trade_levels(
            signal["signal"], current_price, trade["atr"]
        )
        if not risk_plan:
            return current_price

        instrument = get_instrument_spec(symbol)
        equity = float(self.paper_trader.equity)
        quantity = self.risk_manager.position_size(
            equity,
            risk_plan["entry"],
            risk_plan["stop_loss"],
            instrument=instrument,
            side=signal["signal"],
        )
        if quantity <= 0:
            logger.warning("Position size rejected for %s", symbol)
            return current_price

        decision_time = frame_decision_time(
            analyzed, TRADING_TIMEFRAME
        ).to_pydatetime()
        requested_risk = equity * (RISK_PERCENT / 100.0)
        assessment = self.portfolio_risk.assess(
            TradeRiskRequest(
                decision_time=decision_time,
                symbol=symbol,
                direction=signal["signal"],
                requested_quantity=quantity,
                risk_amount=requested_risk,
                equity=equity,
            ),
            self._risk_context(decision_time),
        )
        if not assessment.allowed:
            logger.warning(
                "Portfolio risk blocked %s: %s",
                symbol,
                ", ".join(assessment.reason_codes),
            )
            return current_price

        quantity = assessment.approved_quantity
        self.trade_logger.log_trade(symbol, risk_plan, quantity)
        result = self.execution.execute(
            source_symbol=symbol,
            signal=signal["signal"],
            risk_plan=risk_plan,
            paper_position_size=quantity,
        )
        logger.info("Execution result for %s: %r", symbol, result)
        return current_price

    def run_cycle(self) -> None:
        write_runtime_state(
            status="RUNNING",
            execution_mode=EXECUTION_MODE,
            phase="DOWNLOADING_MARKET_DATA",
            trading_timeframe=TRADING_TIMEFRAME,
            higher_timeframe=HIGHER_TIMEFRAME,
        )
        lower_frames = self.market.download_all_data(
            interval=TRADING_TIMEFRAME
        )
        higher_frames = self.market.download_all_data(
            interval=HIGHER_TIMEFRAME
        )
        prices = {}

        for symbol, data in lower_frames.items():
            if self.controller.status() != "RUNNING":
                break
            try:
                prices[symbol] = self._process_symbol(
                    symbol, data, higher_frames.get(symbol)
                )
            except Exception:
                logger.exception("Cycle failed for %s", symbol)

        self.paper_trader.update_equity(prices)
        now = datetime.now(timezone.utc)
        self.equity_history.append(
            EquityPoint(timestamp=now, equity=self.paper_trader.equity)
        )
        self.equity_history = self.equity_history[-10_000:]
        stats = self.paper_trader.get_stats()
        write_runtime_state(
            status="RUNNING",
            execution_mode=EXECUTION_MODE,
            phase="IDLE",
            equity=stats["equity"],
            balance=stats["balance"],
            open_positions=len(self.execution.positions()),
            closed_trades=stats["total_trades"],
        )

    def run_forever(self) -> None:
        write_runtime_state(
            status="STARTING",
            execution_mode=EXECUTION_MODE,
            phase="STARTING",
        )
        try:
            print(self.controller.start_bot())
            while self.controller.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("AAQTS shutdown requested")
        except Exception as exc:
            write_runtime_state(
                status="ERROR",
                execution_mode=EXECUTION_MODE,
                phase="FAILED",
                error=str(exc),
            )
            raise
        finally:
            if self.controller.is_running:
                self.controller.stop_bot()
            else:
                self.execution.shutdown()
            write_runtime_state(
                status="STOPPED",
                execution_mode=EXECUTION_MODE,
                phase="SHUTDOWN",
            )


def main() -> None:
    TradingApplication().run_forever()


if __name__ == "__main__":
    main()
