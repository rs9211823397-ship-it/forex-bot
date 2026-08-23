"""AAQTS application entry point.

PAPER is the default execution mode. MT5_DEMO requires an explicit environment
setting. MT5_LIVE additionally requires pinned credentials, protected UT Bot
mode and the explicit real-money acknowledgement.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from bot_controller import BotController
from bot_loop import BotLoop
from config.instruments import get_instrument_spec
from config.symbols import symbol_by_data
from config.settings import (
    BOT_INTERVAL_SECONDS,
    EXECUTION_MODE,
    HIGHER_TIMEFRAME,
    MAX_CONSECUTIVE_LOSSES,
    MAX_DAILY_TRADES,
    MAX_DAILY_LOSS_PERCENT,
    MAX_EQUITY_DRAWDOWN_PERCENT,
    MAX_PORTFOLIO_RISK_PERCENT,
    MAX_WEEKLY_LOSS_PERCENT,
    MIN_REGIME_CONFIDENCE,
    MT5_RISK_BASELINE_UTC,
    MT5_MAX_OPEN_POSITIONS,
    MT5_SYMBOL_MAP,
    NEWS_BLOCKED_IMPACTS,
    NEWS_CALENDAR_CACHE,
    NEWS_CALENDAR_FILE,
    NEWS_CALENDAR_URL,
    NEWS_FILTER_ENABLED,
    NEWS_MAX_STALE_MINUTES,
    NEWS_POST_EVENT_MINUTES,
    NEWS_PRE_EVENT_MINUTES,
    NEWS_REFRESH_MINUTES,
    PORTFOLIO_MAX_ABS_CORRELATION,
    PORTFOLIO_MAX_CORRELATED_RISK_PERCENT,
    POSITION_MANAGEMENT_INTERVAL_SECONDS,
    RISK_PERCENT,
    STRATEGY_MODE,
    TRADING_TIMEFRAME,
    UTBOT_ATR_PERIOD,
    UTBOT_BREAK_EVEN_TRIGGER_R,
    UTBOT_EXIT_MODE,
    UTBOT_INITIAL_SL_ATR_MULTIPLIER,
    UTBOT_KEY_VALUE,
    UTBOT_SIGNAL_CONFIDENCE,
    UTBOT_TEST_LOT,
    UTBOT_TRAILING_ATR_MULTIPLIER,
    UTBOT_TRAILING_START_R,
)
from control_plane import ControlAction, ControlCommandStore, ControlRequest
from data.market_data import MarketData
from execution.execution_router import ExecutionRouter
from execution.trade_manager import TradeManager
from indicators.technical import TechnicalIndicators
from logs.logger import TradeLogger
from paper.paper_trader import PaperTrader
from risk.news_calendar import build_news_provider
from risk.portfolio import CorrelationObservation, CurrencyExposure, OpenRiskPosition
from risk.protection import (
    ClosedTradeOutcome,
    EquityPoint,
    PortfolioRiskManager,
    ProtectionConfig,
    RiskContext,
    TradeRiskRequest,
)
from risk.risk_manager import RiskManager
from runtime_state import engine_instance_lock, read_runtime_state, write_runtime_state
from strategy.signal_engine import SignalEngine
from strategy.regime_router import RegimeStrategyRouter
from strategy.ut_bot_ema200 import UTBotConfig, UTBotStrategy


logger = logging.getLogger(__name__)
HEARTBEAT_INTERVAL_SECONDS = 30.0


class TradingApplication:
    """Compose market data, strategy, risk, and execution services."""

    def __init__(self) -> None:
        self.account_id = os.getenv("AAQTS_ACCOUNT_ID", "primary").strip() or "primary"
        command_root = os.getenv("AAQTS_CONTROL_QUEUE_DIR", "runtime/control").strip()
        self.control_commands = ControlCommandStore(command_root)
        self.market = MarketData()
        self.strategy_mode = STRATEGY_MODE
        self.utbot_signal_exit_mode = (
            self.strategy_mode == "UT_BOT"
            and UTBOT_EXIT_MODE == "OPPOSITE_SIGNAL"
        )
        self.utbot_protected_mode = (
            self.strategy_mode == "UT_BOT"
            and UTBOT_EXIT_MODE == "ATR_TRAIL"
        )
        self.utbot_opposite_signal_exit = (
            self.utbot_signal_exit_mode or self.utbot_protected_mode
        )
        if self.strategy_mode == "UT_BOT":
            strategy = UTBotStrategy(
                UTBotConfig(
                    key_value=UTBOT_KEY_VALUE,
                    atr_period=UTBOT_ATR_PERIOD,
                    signal_confidence=UTBOT_SIGNAL_CONFIDENCE,
                )
            )
            self.indicators = strategy
            self.signal_engine = strategy
            self.strategy_router = strategy
            self.requires_higher_timeframe = False
        else:
            self.indicators = TechnicalIndicators()
            self.signal_engine = SignalEngine.production(
                higher_timeframe=HIGHER_TIMEFRAME,
                lower_timeframe=TRADING_TIMEFRAME,
            )
            self.strategy_router = RegimeStrategyRouter(
                self.signal_engine,
                higher_timeframe=HIGHER_TIMEFRAME,
                lower_timeframe=TRADING_TIMEFRAME,
                minimum_regime_confidence=MIN_REGIME_CONFIDENCE,
            )
            self.requires_higher_timeframe = True
        self.trade_manager = TradeManager()
        self.risk_manager = RiskManager()
        self.portfolio_risk = PortfolioRiskManager(
            ProtectionConfig(
                max_daily_loss_percent=MAX_DAILY_LOSS_PERCENT,
                max_weekly_loss_percent=MAX_WEEKLY_LOSS_PERCENT,
                max_equity_drawdown_percent=MAX_EQUITY_DRAWDOWN_PERCENT,
                max_consecutive_losses=MAX_CONSECUTIVE_LOSSES,
                max_daily_trades=MAX_DAILY_TRADES,
                max_open_trades=MT5_MAX_OPEN_POSITIONS,
                max_portfolio_risk_percent=MAX_PORTFOLIO_RISK_PERCENT,
                max_abs_correlation=PORTFOLIO_MAX_ABS_CORRELATION,
                max_correlated_risk_percent=PORTFOLIO_MAX_CORRELATED_RISK_PERCENT,
                news_filter_enabled=NEWS_FILTER_ENABLED,
                fail_closed_on_news_error=True,
                blocked_news_impacts=NEWS_BLOCKED_IMPACTS,
                news_pre_event_buffer=timedelta(minutes=NEWS_PRE_EVENT_MINUTES),
                news_post_event_buffer=timedelta(minutes=NEWS_POST_EVENT_MINUTES),
            )
        )
        self.news_provider = build_news_provider(
            enabled=NEWS_FILTER_ENABLED,
            calendar_file=NEWS_CALENDAR_FILE,
            calendar_url=NEWS_CALENDAR_URL,
            cache_path=NEWS_CALENDAR_CACHE,
            refresh_minutes=NEWS_REFRESH_MINUTES,
            max_stale_minutes=NEWS_MAX_STALE_MINUTES,
        )
        self.paper_trader = PaperTrader()
        self.execution = ExecutionRouter(self.paper_trader)
        self.trade_logger = TradeLogger()
        self.equity_history: list[EquityPoint] = []
        self._previous_runtime_state = read_runtime_state()
        saved_signal_ids = self._previous_runtime_state.get("executed_signal_ids", {})
        self._executed_signal_ids = (
            {
                str(symbol): str(signal_id)
                for symbol, signal_id in saved_signal_ids.items()
                if str(symbol).strip() and str(signal_id).strip()
            }
            if isinstance(saved_signal_ids, dict)
            else {}
        )
        self._risk_state_identity = ""
        self._cycle_stages: Counter[str] = Counter()
        self._session_stages: Counter[str] = Counter()
        self._cycle_reasons: Counter[str] = Counter()
        self._session_reasons: Counter[str] = Counter()
        self._telemetry_lock = threading.RLock()
        self.latest_atr_by_symbol: dict[str, float] = {}
        self._atr_lock = threading.RLock()
        self._last_management_report: dict[str, object] = {}
        self._management_report_lock = threading.RLock()
        self.latest_correlations: tuple[CorrelationObservation, ...] = ()
        self._latest_analysis_by_symbol: dict[str, dict[str, object]] = {}
        self._analysis_lock = threading.RLock()
        self.loop = BotLoop(interval=BOT_INTERVAL_SECONDS)
        self.management_loop = BotLoop(
            interval=POSITION_MANAGEMENT_INTERVAL_SECONDS,
            max_consecutive_failures=10,
        )
        self.controller = BotController.configured(
            bot_loop=self.loop,
            execution_router=self.execution,
            callback=self.run_cycle,
            management_loop=self.management_loop,
            management_callback=self.run_position_management_cycle,
        )

    def _record_decision_stage(self, stage: str, reason: object = None) -> None:
        normalized_stage = str(stage).strip().upper() or "UNKNOWN"
        with self._telemetry_lock:
            self._cycle_stages[normalized_stage] += 1
            self._session_stages[normalized_stage] += 1
            if reason is None:
                return
            reasons = reason if isinstance(reason, (list, tuple, set)) else (reason,)
            for item in reasons:
                text = " ".join(str(item).strip().split())
                if not text:
                    continue
                key = f"{normalized_stage}:{text}"[:240]
                self._cycle_reasons[key] += 1
                self._session_reasons[key] += 1

    def _decision_telemetry(self) -> dict[str, object]:
        with self._telemetry_lock:
            return {
                "cycle_stages": dict(self._cycle_stages.most_common()),
                "session_stages": dict(self._session_stages.most_common()),
                "cycle_reasons": dict(self._cycle_reasons.most_common(20)),
                "session_reasons": dict(self._session_reasons.most_common(50)),
            }

    def _record_runtime_analysis(
        self,
        symbol: str,
        signal: dict,
        *,
        final_decision: str | None = None,
        final_reason: object = None,
        risk_plan: dict | None = None,
        portfolio_action: object = None,
        execution_status: str | None = None,
    ) -> None:
        report = signal.get("decision_report") or {}
        reasons = signal.get("reasons") or report.get("reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]

        strategy_signal = str(signal.get("signal", "HOLD")).upper()

        if final_decision is None:
            final_decision = (
                "PENDING"
                if strategy_signal in {"BUY", "SELL"}
                else "HOLD"
            )

        if final_reason is None:
            final_reason = (
                report.get("primary_reason")
                or (reasons[0] if reasons else "No actionable setup")
            )

        entry = None
        stop_loss = None
        take_profit = None
        risk_reward = None

        if isinstance(risk_plan, dict):
            entry = risk_plan.get("entry")
            stop_loss = risk_plan.get("stop_loss")
            take_profit = (
                risk_plan.get("take_profit")
                if "take_profit" in risk_plan
                else risk_plan.get("tp")
            )

            try:
                if (
                    entry is not None
                    and stop_loss is not None
                    and take_profit is not None
                    and float(take_profit) > 0
                ):
                    risk = abs(float(entry) - float(stop_loss))
                    reward = abs(float(take_profit) - float(entry))
                    if risk > 0:
                        risk_reward = reward / risk
            except (TypeError, ValueError):
                risk_reward = None

        summary = {
            "symbol": str(symbol),
            "strategy_signal": strategy_signal,
            "signal": strategy_signal,
            "final_decision": str(final_decision),
            "final_reason": str(final_reason),
            "confidence": float(signal.get("confidence", 0) or 0),
            "strategy": str(
                signal.get("strategy")
                or report.get("strategy")
                or "UNKNOWN"
            ),
            "regime": str(
                signal.get("regime")
                or report.get("regime")
                or "UNKNOWN"
            ),
            "higher_timeframe_bias": str(
                signal.get("higher_timeframe_bias")
                or signal.get("higher_timeframe")
                or signal.get("htf_regime")
                or signal.get("htf")
                or report.get("higher_timeframe_bias")
                or report.get("higher_timeframe")
                or report.get("htf_regime")
                or report.get("htf")
                or "UNKNOWN"
            ),
            "primary_reason": str(
                report.get("primary_reason")
                or (reasons[0] if reasons else "No actionable setup")
            ),
            "reasons": [str(item) for item in list(reasons)[:6]],
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward": risk_reward,
            "portfolio_action": (
                str(portfolio_action)
                if portfolio_action is not None
                else None
            ),
            "execution_status": execution_status,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }

        with self._analysis_lock:
            self._latest_analysis_by_symbol[str(symbol)] = summary

    @staticmethod
    def _closed_trade_stats(closed_results) -> dict[str, float | int]:
        results = tuple(closed_results)
        wins = sum(item.profit_loss > 0 for item in results)
        losses = sum(item.profit_loss < 0 for item in results)
        return {
            "closed_trades": len(results),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(results) * 100.0 if results else 0.0,
        }

    def _runtime_risk_identity(self, account) -> str:
        """Bind persisted drawdown state to one account and risk epoch."""

        baseline = (
            MT5_RISK_BASELINE_UTC.isoformat()
            if MT5_RISK_BASELINE_UTC is not None
            else "UNSET"
        )
        if self.execution.mode == "PAPER":
            broker_identity = f"paper:{self.account_id}"
        else:
            login = getattr(account, "login", None)
            server = str(getattr(account, "server", "")).strip()
            if login is None or not server:
                raise RuntimeError(
                    "Broker account identity is unavailable; persisted risk state cannot be trusted"
                )
            broker_identity = f"mt5:{int(login)}:{server.casefold()}"
        return f"{self.execution.mode}:{broker_identity}:baseline:{baseline}"

    def _initialize_equity_state(self, account, observed_at: datetime) -> None:
        """Restore a peak only when the persisted account epoch is identical."""

        if self._risk_state_identity:
            return
        identity = self._runtime_risk_identity(account)
        previous = self._previous_runtime_state
        previous_identity = str(previous.get("risk_state_identity", "")).strip()
        previous_peak = 0.0
        try:
            previous_peak = float(previous.get("equity_peak", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass

        current_equity = float(account.equity)
        restored_peak = (
            previous_peak
            if previous_identity == identity and previous_peak >= current_equity
            else current_equity
        )
        self.equity_history = [
            EquityPoint(timestamp=observed_at, equity=restored_peak)
        ]
        self._risk_state_identity = identity
        if previous_peak > 0 and previous_identity != identity:
            logger.warning(
                "Discarded stale equity peak %.2f because runtime risk identity changed",
                previous_peak,
            )

    def _record_equity(self, account, observed_at: datetime) -> None:
        self._initialize_equity_state(account, observed_at)
        self.equity_history.append(
            EquityPoint(timestamp=observed_at, equity=float(account.equity))
        )
        self.equity_history = self.equity_history[-10_000:]

    def _handle_control_request(self, request: ControlRequest) -> str:
        if request.account_id != self.account_id:
            raise ValueError("Control request targeted a different account")
        if request.action is ControlAction.PAUSE_ENTRIES:
            result = self.controller.pause_bot()
        elif request.action is ControlAction.RESUME_ENTRIES:
            result = self.controller.resume_bot()
        elif request.action is ControlAction.STOP_ENGINE:
            result = self.controller.stop_bot()
        elif request.action is ControlAction.EMERGENCY_CLOSE:
            closed = self.controller.emergency_stop()
            result = f"EMERGENCY STOP COMPLETED; CLOSED {len(closed)} POSITIONS"
        else:
            raise ValueError(f"Unsupported control action: {request.action}")
        write_runtime_state(
            account_id=self.account_id,
            status=self.controller.status(),
            phase=f"CONTROL_{request.action.value}",
            last_control_request=request.request_id,
        )
        return result

    def _process_control_commands(self) -> None:
        results = self.control_commands.process_available(
            self.account_id, self._handle_control_request
        )
        for request, result, success in results:
            (logger.info if success else logger.error)(
                "Control request %s (%s) result: %s",
                request.request_id,
                request.action.value,
                result,
            )

    @staticmethod
    def _parse_time(value: object, fallback: datetime) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, (int, float)):
            try:
                parsed = datetime.fromtimestamp(float(value), timezone.utc)
            except (OverflowError, OSError, ValueError):
                return fallback
        else:
            try:
                parsed = datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                return fallback
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _currency_exposures(source_symbol: str, direction: str) -> tuple[CurrencyExposure, ...]:
        try:
            definition = symbol_by_data(source_symbol)
            base, quote = definition.base_asset, definition.quote_asset
        except KeyError:
            return ()
        if base == quote:
            return ()
        base_direction = 1 if direction == "BUY" else -1
        return (
            CurrencyExposure(base, base_direction),
            CurrencyExposure(quote, -base_direction),
        )

    @staticmethod
    def _source_symbol(broker_symbol: str) -> str:
        normalized = str(broker_symbol).strip().upper()
        for source, broker in MT5_SYMBOL_MAP.items():
            if str(broker).strip().upper() == normalized:
                return source
        return normalized

    @staticmethod
    def _frame_is_demo_safe(frame) -> bool:
        return bool(
            frame is not None
            and not getattr(frame, "empty", True)
            and getattr(frame, "attrs", {}).get("source") == "MT5"
            and getattr(frame, "attrs", {}).get("fresh") is True
        )

    @staticmethod
    def _build_correlations(
        frames: dict[str, object], observed_at: datetime
    ) -> tuple[CorrelationObservation, ...]:
        symbols = sorted(frames)
        observations: list[CorrelationObservation] = []
        for index, first in enumerate(symbols):
            first_frame = frames[first]
            if getattr(first_frame, "empty", True) or "close" not in first_frame:
                continue
            first_returns = first_frame["close"].astype(float).pct_change().dropna().tail(120)
            for second in symbols[index + 1 :]:
                second_frame = frames[second]
                if getattr(second_frame, "empty", True) or "close" not in second_frame:
                    continue
                second_returns = second_frame["close"].astype(float).pct_change().dropna().tail(120)
                aligned = (
                    first_returns.to_frame("first")
                    .join(second_returns.to_frame("second"), how="inner")
                    .dropna()
                )
                if len(aligned) < 30:
                    continue
                value = float(aligned["first"].corr(aligned["second"]))
                if value != value:
                    continue
                observations.append(
                    CorrelationObservation(
                        first_symbol=first,
                        second_symbol=second,
                        observed_at=observed_at,
                        correlation=max(-1.0, min(1.0, value)),
                    )
                )
        return tuple(observations)

    def _account_equity(self) -> float:
        return self.execution.account_snapshot().equity

    def _risk_context(self, decision_time: datetime) -> RiskContext:
        if self.execution.mode in {"MT5_DEMO", "MT5_LIVE"}:
            return self._mt5_risk_context(decision_time)
        positions = []
        for trade in self.paper_trader.open_trades:
            try:
                instrument = get_instrument_spec(trade["symbol"])
                quantity = float(trade["position"])
                risk_amount = instrument.planned_loss_per_quantity(
                    entry_reference=trade.get("entry_reference", trade["entry"]),
                    stop_reference=trade["stop_loss"],
                    side=trade["signal"],
                ) * quantity
                positions.append(
                    OpenRiskPosition(
                        symbol=trade["symbol"],
                        direction=trade["signal"],
                        opened_at=self._parse_time(trade.get("opened_at"), decision_time),
                        risk_amount=risk_amount,
                        quantity=quantity,
                        strategy="aaqts",
                        currency_exposures=self._currency_exposures(
                            trade["symbol"], trade["signal"]
                        ),
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
                    closed_at=self._parse_time(trade["closed_at"], decision_time),
                    profit_loss=float(trade.get("pnl", 0.0)),
                )
            )
        return RiskContext(
            open_positions=tuple(positions),
            closed_trades=tuple(closed),
            equity_history=tuple(self.equity_history),
            correlations=self.latest_correlations,
            news_provider=self.news_provider,
        )

    def _mt5_risk_context(self, decision_time: datetime) -> RiskContext:
        positions = []
        for position in self.execution.positions():
            source_symbol = self._source_symbol(position.symbol)
            direction = self.execution.position_side(position)
            positions.append(
                OpenRiskPosition(
                    symbol=source_symbol,
                    direction=direction,
                    opened_at=self._parse_time(getattr(position, "time", None), decision_time),
                    risk_amount=self.execution.remaining_loss_at_stop(position),
                    quantity=float(getattr(position, "volume", 0.0)),
                    strategy="aaqts",
                    currency_exposures=self._currency_exposures(source_symbol, direction),
                )
            )
        history_start = decision_time - timedelta(days=8)
        closed = tuple(
            ClosedTradeOutcome(
                closed_at=result.closed_at,
                profit_loss=result.profit_loss,
            )
            for result in self.execution.closed_position_results(history_start, decision_time)
        )
        return RiskContext(
            open_positions=tuple(positions),
            closed_trades=closed,
            equity_history=tuple(self.equity_history),
            correlations=self.latest_correlations,
            news_provider=self.news_provider,
        )

    def _process_symbol(self, symbol, data, higher_tf) -> float:
        self._record_decision_stage("SYMBOL_SCANNED")
        if self.execution.mode in {"MT5_DEMO", "MT5_LIVE"}:
            if not self._frame_is_demo_safe(data):
                raise RuntimeError(f"Unsafe/stale lower-timeframe data blocked for {symbol}")
            if self.requires_higher_timeframe and not self._frame_is_demo_safe(higher_tf):
                raise RuntimeError(f"Unsafe/stale higher-timeframe data blocked for {symbol}")
        analyzed = self.indicators.add_indicators(data)
        signal = self.strategy_router.generate_analysis(analyzed, symbol, higher_tf)
        self._record_runtime_analysis(symbol, signal)
        trade = self.trade_manager.calculate_trade(analyzed, signal)
        current_price = float(trade["current_price"])
        with self._atr_lock:
            self.latest_atr_by_symbol[symbol] = float(trade["atr"])
        self.trade_logger.log_signal(symbol, signal["signal"], signal["confidence"])
        if self.execution.mode == "PAPER":
            self.paper_trader.check_trade(symbol, current_price)
        exit_signal = str(signal.get("exit_signal") or "").upper().strip()
        if self.utbot_opposite_signal_exit and exit_signal in {"BUY", "SELL"}:
            try:
                closed = self.execution.close_on_opposite_signal(
                    symbol,
                    exit_signal,
                    current_price=current_price,
                )
            except Exception as exc:
                self._record_decision_stage(
                    "SIGNAL_EXIT_FAILED",
                    f"{type(exc).__name__}: {exc}",
                )
                self._record_runtime_analysis(
                    symbol,
                    signal,
                    final_decision="BLOCKED",
                    final_reason=f"Opposite-signal close failed: {exc}",
                    execution_status="SIGNAL_EXIT_FAILED",
                )
                raise
            if closed:
                self._record_decision_stage("SIGNAL_EXIT_EXECUTED", exit_signal)
                self._record_runtime_analysis(
                    symbol,
                    signal,
                    final_decision=(
                        "PENDING_REVERSAL"
                        if signal["signal"] in {"BUY", "SELL"}
                        else "EXITED"
                    ),
                    final_reason=f"Closed on opposite UT Bot {exit_signal} signal",
                    execution_status="SIGNAL_EXIT_EXECUTED",
                )
        if signal["signal"] not in {"BUY", "SELL"}:
            report = signal.get("decision_report") or {}
            primary = report.get("primary_reason") or "NO_ACTIONABLE_SETUP"
            self._record_decision_stage("STRATEGY_HOLD", primary)
            self._record_runtime_analysis(
                symbol,
                signal,
                final_decision="HOLD",
                final_reason=primary,
                execution_status="NOT_ACTIONABLE",
            )
            return current_price
        signal_id = str(signal.get("signal_id") or "").strip()
        if signal_id and self._executed_signal_ids.get(str(symbol)) == signal_id:
            reason = "UT Bot crossover was already executed for this candle"
            self._record_decision_stage("DUPLICATE_SIGNAL_BLOCKED", reason)
            self._record_runtime_analysis(
                symbol,
                signal,
                final_decision="BLOCKED",
                final_reason=reason,
                execution_status="DUPLICATE_SIGNAL_BLOCKED",
            )
            return current_price
        self._record_decision_stage("STRATEGY_ACTIONABLE", signal["signal"])
        if self.utbot_signal_exit_mode:
            signal_plan = {
                "entry": current_price,
                "stop_loss": 0.0,
                "take_profit": 0.0,
            }
            self._record_runtime_analysis(
                symbol,
                signal,
                final_decision="APPROVED",
                final_reason="UT Bot entry approved",
                risk_plan=signal_plan,
                execution_status="SIGNAL_ENTRY_ATTEMPT",
            )
            self._record_decision_stage("EXECUTION_ATTEMPT", signal["signal"])
            try:
                result = self.execution.execute(
                    source_symbol=symbol,
                    signal=signal["signal"],
                    risk_plan=signal_plan,
                    paper_position_size=UTBOT_TEST_LOT,
                    approved_risk_amount=None,
                )
            except Exception as exc:
                self._record_decision_stage(
                    "EXECUTION_REJECTED",
                    f"{type(exc).__name__}: {exc}",
                )
                self._record_runtime_analysis(
                    symbol,
                    signal,
                    final_decision="BLOCKED",
                    final_reason=f"{type(exc).__name__}: {exc}",
                    risk_plan=signal_plan,
                    execution_status="EXECUTION_REJECTED",
                )
                raise
            if result is None:
                self._record_decision_stage(
                    "EXECUTION_REJECTED",
                    "EXECUTOR_RETURNED_NO_POSITION",
                )
                return current_price
            if signal_id:
                self._executed_signal_ids[str(symbol)] = signal_id
            self._record_decision_stage("EXECUTED", signal["signal"])
            self._record_runtime_analysis(
                symbol,
                signal,
                final_decision="EXECUTED",
                final_reason="Trade opened; next opposite UT signal is the exit",
                risk_plan=signal_plan,
                execution_status="EXECUTED_SIGNAL_LIFECYCLE",
            )
            logger.info("Signal-lifecycle execution result for %s: %r", symbol, result)
            return current_price
        risk_plan = self.risk_manager.calculate_trade_levels(
            signal["signal"],
            current_price,
            trade["atr"],
            stop_atr_multiplier=(
                UTBOT_INITIAL_SL_ATR_MULTIPLIER
                if self.utbot_protected_mode
                else None
            ),
        )
        if not risk_plan:
            self._record_decision_stage("TRADE_LEVEL_REJECTED", "INVALID_RISK_PLAN")
            self._record_runtime_analysis(
                symbol,
                signal,
                final_decision="BLOCKED",
                final_reason="INVALID_RISK_PLAN",
                execution_status="RISK_PLAN_REJECTED",
            )
            return current_price
        if self.utbot_protected_mode:
            # No fixed TP caps a strong trend. The broker-side SL bounds the
            # initial loss, then the management loop moves it to break-even
            # and advances an ATR trail. A confirmed opposite UT crossover
            # remains the final signal exit.
            risk_plan["take_profit"] = 0.0
            risk_plan["reward_distance"] = 0.0
            risk_plan["risk_reward"] = 0.0
        equity = self._account_equity()
        risk_multiplier = float(signal.get("risk_multiplier", 1.0))
        requested_risk = equity * (RISK_PERCENT / 100.0) * risk_multiplier
        if self.execution.mode == "PAPER":
            instrument = get_instrument_spec(symbol)
            requested_quantity = self.risk_manager.position_size(
                equity,
                risk_plan["entry"],
                risk_plan["stop_loss"],
                instrument=instrument,
                side=signal["signal"],
                risk_multiplier=risk_multiplier,
            )
            if requested_quantity <= 0:
                self._record_decision_stage("SIZING_REJECTED", "NON_POSITIVE_PAPER_SIZE")
                self._record_runtime_analysis(
                    symbol,
                    signal,
                    final_decision="BLOCKED",
                    final_reason="NON_POSITIVE_PAPER_SIZE",
                    risk_plan=risk_plan,
                    execution_status="SIZING_REJECTED",
                )
                logger.warning(
                    "Paper position size rejected for %s (equity=%.2f requested_risk=%.2f)",
                    symbol,
                    equity,
                    requested_risk,
                )
                return current_price
        else:
            requested_quantity = 1.0
        decision_time = datetime.now(timezone.utc)
        assessment = self.portfolio_risk.assess(
            TradeRiskRequest(
                decision_time=decision_time,
                symbol=symbol,
                direction=signal["signal"],
                requested_quantity=requested_quantity,
                risk_amount=requested_risk,
                equity=equity,
                volatility_ratio=float(trade["atr"]) / current_price,
                currency_exposures=self._currency_exposures(symbol, signal["signal"]),
            ),
            self._risk_context(decision_time),
        )
        if not assessment.allowed:
            self._record_decision_stage("PORTFOLIO_RISK_BLOCKED", assessment.reason_codes)
            self._record_runtime_analysis(
                symbol,
                signal,
                final_decision="BLOCKED",
                final_reason=", ".join(assessment.reason_codes),
                risk_plan=risk_plan,
                portfolio_action=getattr(assessment.action, "value", assessment.action),
                execution_status="PORTFOLIO_RISK_BLOCKED",
            )
            logger.warning(
                "Portfolio risk blocked %s: %s",
                symbol,
                ", ".join(assessment.reason_codes),
            )
            return current_price
        if self.execution.mode == "PAPER":
            approved_quantity = assessment.approved_quantity
            self.trade_logger.log_trade(symbol, risk_plan, approved_quantity)
        else:
            approved_quantity = requested_quantity
            logger.info(
                "MT5 broker sizing approved for %s: risk_amount=%.2f portfolio_action=%s",
                symbol,
                assessment.approved_risk_amount,
                assessment.action.value,
            )
        self._record_runtime_analysis(
            symbol,
            signal,
            final_decision="APPROVED",
            final_reason="All pre-execution checks passed",
            risk_plan=risk_plan,
            portfolio_action=getattr(assessment.action, "value", assessment.action),
            execution_status="EXECUTION_ATTEMPT",
        )
        self._record_decision_stage("EXECUTION_ATTEMPT", signal["signal"])
        try:
            result = self.execution.execute(
                source_symbol=symbol,
                signal=signal["signal"],
                risk_plan=risk_plan,
                paper_position_size=approved_quantity,
                approved_risk_amount=assessment.approved_risk_amount,
            )
        except Exception as exc:
            self._record_decision_stage(
                "EXECUTION_REJECTED",
                f"{type(exc).__name__}: {exc}",
            )
            self._record_runtime_analysis(
                symbol,
                signal,
                final_decision="BLOCKED",
                final_reason=f"{type(exc).__name__}: {exc}",
                risk_plan=risk_plan,
                portfolio_action=getattr(assessment.action, "value", assessment.action),
                execution_status="EXECUTION_REJECTED",
            )
            raise
        if result is None:
            self._record_decision_stage(
                "EXECUTION_REJECTED",
                "EXECUTOR_RETURNED_NO_POSITION",
            )
            self._record_runtime_analysis(
                symbol,
                signal,
                final_decision="BLOCKED",
                final_reason="EXECUTOR_RETURNED_NO_POSITION",
                risk_plan=risk_plan,
                portfolio_action=getattr(assessment.action, "value", assessment.action),
                execution_status="EXECUTION_REJECTED",
            )
            logger.warning("Execution produced no new position for %s", symbol)
            return current_price
        self._record_decision_stage("EXECUTED", signal["signal"])
        if signal_id:
            self._executed_signal_ids[str(symbol)] = signal_id
        self._record_runtime_analysis(
            symbol,
            signal,
            final_decision="EXECUTED",
            final_reason="Trade executed",
            risk_plan=risk_plan,
            portfolio_action=getattr(assessment.action, "value", assessment.action),
            execution_status="EXECUTED",
        )
        logger.info("Execution result for %s: %r", symbol, result)
        return current_price

    def run_position_management_cycle(self) -> None:
        with self._atr_lock:
            latest_atr = dict(self.latest_atr_by_symbol)
        report = self.execution.manage_positions(latest_atr)
        with self._management_report_lock:
            self._last_management_report = dict(report)
        if report.get("errors"):
            self._record_decision_stage("POSITION_MANAGEMENT_ERROR", report["errors"])
            logger.error("Position-management errors: %s", report["errors"])

    def run_cycle(self) -> None:
        with self._atr_lock:
            self.latest_atr_by_symbol = {}
        with self._telemetry_lock:
            self._cycle_stages.clear()
            self._cycle_reasons.clear()
        cycle_account = self.execution.account_snapshot()
        self._record_equity(cycle_account, datetime.now(timezone.utc))
        write_runtime_state(
            account_id=self.account_id,
            status=self.controller.status(),
            execution_mode=EXECUTION_MODE,
            phase="DOWNLOADING_MARKET_DATA",
            strategy_mode=self.strategy_mode,
            utbot_exit_mode=UTBOT_EXIT_MODE,
            utbot_test_lot=(UTBOT_TEST_LOT if self.utbot_signal_exit_mode else None),
            utbot_initial_sl_atr=(
                UTBOT_INITIAL_SL_ATR_MULTIPLIER
                if self.utbot_protected_mode
                else None
            ),
            utbot_break_even_trigger_r=(
                UTBOT_BREAK_EVEN_TRIGGER_R
                if self.utbot_protected_mode
                else None
            ),
            utbot_trailing_start_r=(
                UTBOT_TRAILING_START_R if self.utbot_protected_mode else None
            ),
            utbot_trailing_atr=(
                UTBOT_TRAILING_ATR_MULTIPLIER
                if self.utbot_protected_mode
                else None
            ),
            scan_interval_seconds=BOT_INTERVAL_SECONDS,
            trading_timeframe=TRADING_TIMEFRAME,
            higher_timeframe=(
                HIGHER_TIMEFRAME if self.requires_higher_timeframe else "NOT_USED"
            ),
            market_data_provider=self.market.provider,
        )
        lower_frames = self.market.download_all_data(interval=TRADING_TIMEFRAME)
        higher_frames = (
            self.market.download_all_data(interval=HIGHER_TIMEFRAME)
            if self.requires_higher_timeframe
            else {}
        )
        observed_at = datetime.now(timezone.utc)
        self.latest_correlations = self._build_correlations(lower_frames, observed_at)
        prices = {}
        broker_mode = self.execution.mode in {"MT5_DEMO", "MT5_LIVE"}
        expected = set(MT5_SYMBOL_MAP) if broker_mode else set(lower_frames)
        missing_lower = sorted(expected.difference(lower_frames))
        missing_higher = (
            sorted(expected.difference(higher_frames))
            if self.requires_higher_timeframe
            else []
        )
        if broker_mode and (missing_lower or missing_higher):
            self._record_decision_stage(
                "MARKET_DATA_BLOCKED",
                tuple(f"LOWER:{item}" for item in missing_lower)
                + tuple(f"HIGHER:{item}" for item in missing_higher),
            )
            logger.error(
                "Broker data health degraded; affected symbols will fail closed | lower=%s higher=%s",
                missing_lower,
                missing_higher,
            )
        for symbol, data in lower_frames.items():
            if self.controller.status() != "RUNNING":
                break
            if broker_mode and self.requires_higher_timeframe and symbol not in higher_frames:
                logger.error("Skipping %s: required higher-timeframe data unavailable", symbol)
                continue
            try:
                prices[symbol] = self._process_symbol(symbol, data, higher_frames.get(symbol))
            except Exception:
                self._record_decision_stage("SYMBOL_ERROR", symbol)
                logger.exception("Cycle failed for %s", symbol)
        if self.execution.mode == "PAPER":
            self.paper_trader.update_equity(prices)
        now = datetime.now(timezone.utc)
        account = self.execution.account_snapshot()
        self._record_equity(account, now)
        equity_peak = max(point.equity for point in self.equity_history)
        if self.execution.mode == "PAPER":
            stats = self.paper_trader.get_stats()
            closed_trades = stats["total_trades"]
            closed_window = "all"
        else:
            closed_results = self.execution.closed_position_results(
                now - timedelta(days=7), now
            )
            closed_stats = self._closed_trade_stats(closed_results)
            stats = {
                "equity": account.equity,
                "balance": account.balance,
                "wins": closed_stats["wins"],
                "losses": closed_stats["losses"],
                "win_rate": closed_stats["win_rate"],
            }
            closed_trades = int(closed_stats["closed_trades"])
            closed_window = "7d"
        with self._management_report_lock:
            management_report = dict(self._last_management_report)

        raw_positions = list(self.execution.positions())
        runtime_positions = []
        for position in raw_positions:
            if isinstance(position, dict):
                runtime_positions.append(dict(position))
                continue
            runtime_positions.append(
                {
                    "ticket": getattr(position, "ticket", None),
                    "symbol": getattr(position, "symbol", "Unknown"),
                    "type": getattr(position, "type", None),
                    "volume": getattr(position, "volume", None),
                    "price_open": getattr(position, "price_open", None),
                    "price_current": getattr(position, "price_current", None),
                    "sl": getattr(position, "sl", None),
                    "tp": getattr(position, "tp", None),
                    "profit": float(getattr(position, "profit", 0.0) or 0.0),
                    "magic": getattr(position, "magic", None),
                }
            )

        with self._analysis_lock:
            analysis_snapshot = [
                dict(item)
                for _, item in sorted(self._latest_analysis_by_symbol.items())
            ]

        write_runtime_state(
            account_id=self.account_id,
            status=self.controller.status(),
            execution_mode=EXECUTION_MODE,
            strategy_mode=self.strategy_mode,
            utbot_exit_mode=UTBOT_EXIT_MODE,
            utbot_test_lot=(UTBOT_TEST_LOT if self.utbot_signal_exit_mode else None),
            utbot_initial_sl_atr=(
                UTBOT_INITIAL_SL_ATR_MULTIPLIER
                if self.utbot_protected_mode
                else None
            ),
            utbot_break_even_trigger_r=(
                UTBOT_BREAK_EVEN_TRIGGER_R
                if self.utbot_protected_mode
                else None
            ),
            utbot_trailing_start_r=(
                UTBOT_TRAILING_START_R if self.utbot_protected_mode else None
            ),
            utbot_trailing_atr=(
                UTBOT_TRAILING_ATR_MULTIPLIER
                if self.utbot_protected_mode
                else None
            ),
            scan_interval_seconds=BOT_INTERVAL_SECONDS,
            phase="IDLE",
            market_data_provider=self.market.provider,
            market_data_healthy=not (missing_lower or missing_higher),
            missing_lower_symbols=missing_lower,
            missing_higher_symbols=missing_higher,
            correlation_observations=len(self.latest_correlations),
            equity=stats["equity"],
            equity_peak=equity_peak,
            risk_state_identity=self._risk_state_identity,
            mt5_login=account.login,
            mt5_server=account.server,
            risk_baseline_utc=(
                MT5_RISK_BASELINE_UTC.isoformat()
                if MT5_RISK_BASELINE_UTC is not None
                else None
            ),
            balance=stats["balance"],
            floating_pnl=(
                stats["floating_pnl"]
                if self.execution.mode == "PAPER"
                else account.equity - account.balance
            ),
            open_positions=len(runtime_positions),
            positions=runtime_positions,
            latest_analysis=analysis_snapshot,
            analysis_updated_utc=now.isoformat(),
            executed_signal_ids=dict(self._executed_signal_ids),
            closed_trades=closed_trades,
            closed_trades_window=closed_window,
            starting_balance=stats.get("starting_balance", stats["balance"]),
            wins=stats.get("wins", 0),
            losses=stats.get("losses", 0),
            win_rate=stats.get("win_rate", 0.0),
            decision_telemetry=self._decision_telemetry(),
            position_management={
                "interval_seconds": POSITION_MANAGEMENT_INTERVAL_SECONDS,
                "last_cycle": management_report,
            },
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    app = TradingApplication()
    with engine_instance_lock(app.account_id):
        try:
            app.controller.start_bot()
            next_heartbeat = 0.0
            while app.controller.status() != "STOPPED":
                app._process_control_commands()
                now = time.monotonic()
                if now >= next_heartbeat:
                    write_runtime_state(
                        account_id=app.account_id,
                        status=app.controller.status(),
                        execution_mode=EXECUTION_MODE,
                    )
                    next_heartbeat = now + HEARTBEAT_INTERVAL_SECONDS
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("AAQTS shutdown requested")
        finally:
            app.controller.stop_bot()
            write_runtime_state(
                account_id=app.account_id,
                status="STOPPED",
                phase="STOPPED",
                execution_mode=EXECUTION_MODE,
            )


if __name__ == "__main__":
    main()
