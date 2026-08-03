from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
import hashlib
import inspect
import logging
import math
import threading
import time as time_module
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Optional, Sequence


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class TradeStatus(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"


@dataclass(slots=True)
class TradeManagerConfig:
    enabled: bool = True
    dry_run: bool = False
    allow_buy: bool = True
    allow_sell: bool = True
    minimum_signal_confidence: float = 0.0
    minimum_trade_quality: float = 55.0
    maximum_spread_points: Optional[float] = None
    maximum_slippage_points: Optional[float] = None
    maximum_open_positions: int = 5
    maximum_positions_per_symbol: int = 1
    cooldown_seconds: int = 15 * 60
    duplicate_window_seconds: int = 60
    one_direction_per_symbol: bool = True
    block_opposite_direction: bool = True
    require_stop_loss: bool = True
    require_take_profit: bool = True
    comment_prefix: str = "AAQTS"
    magic_number: Optional[int] = None
    default_symbol: Optional[str] = None
    allowed_sessions: tuple[str, ...] = ("LONDON", "NEW_YORK", "OVERLAP")
    session_filter_enabled: bool = False
    utc_session_hours: Mapping[str, tuple[int, int]] = field(
        default_factory=lambda: {
            "ASIA": (0, 8),
            "LONDON": (7, 16),
            "NEW_YORK": (12, 21),
            "OVERLAP": (12, 16),
        }
    )
    symbol_correlation_groups: tuple[tuple[str, ...], ...] = (
        ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"),
        ("USDCHF", "USDCAD", "USDJPY"),
        ("XAUUSD", "XAGUSD"),
    )
    maximum_correlated_positions: int = 2
    fail_closed: bool = True
    raise_on_internal_error: bool = False

    def __post_init__(self) -> None:
        self.minimum_signal_confidence = _clamp(float(self.minimum_signal_confidence), 0.0, 100.0)
        self.minimum_trade_quality = _clamp(float(self.minimum_trade_quality), 0.0, 100.0)
        self.maximum_open_positions = max(1, int(self.maximum_open_positions))
        self.maximum_positions_per_symbol = max(1, int(self.maximum_positions_per_symbol))
        self.cooldown_seconds = max(0, int(self.cooldown_seconds))
        self.duplicate_window_seconds = max(0, int(self.duplicate_window_seconds))
        self.maximum_correlated_positions = max(1, int(self.maximum_correlated_positions))


@dataclass(slots=True)
class TradeRequest:
    symbol: str
    signal: str
    entry_price: float
    atr: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 100.0
    quality_score: Optional[float] = None
    timeframe: Optional[str] = None
    strategy: Optional[str] = None
    spread_points: Optional[float] = None
    slippage_points: Optional[float] = None
    account_balance: Optional[float] = None
    account_equity: Optional[float] = None
    daily_profit_loss: float = 0.0
    consecutive_losses: int = 0
    risk_multiplier: float = 1.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    volume: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_side(self) -> TradeSide:
        return normalize_signal(self.signal)

    def fingerprint(self) -> str:
        raw = "|".join(
            [
                self.symbol.upper().strip(),
                self.normalized_side().value,
                self.timeframe or "",
                self.strategy or "",
                str(self.metadata.get("signal_id", "")),
            ]
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        return result


@dataclass(slots=True)
class TradeDecision:
    approved: bool
    status: TradeStatus
    request: TradeRequest
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    risk: dict[str, Any] = field(default_factory=dict)
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    volume: Optional[float] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "status": self.status.value,
            "request": self.request.to_dict(),
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "risk": dict(self.risk),
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "volume": self.volume,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(slots=True)
class TradeOutcome:
    success: bool
    status: TradeStatus
    decision: TradeDecision
    execution_result: Any = None
    position_ticket: Optional[int] = None
    error: Optional[str] = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "success": self.success,
            "status": self.status.value,
            "decision": self.decision.to_dict(),
            "position_ticket": self.position_ticket,
            "error": self.error,
            "completed_at": self.completed_at.isoformat(),
        }
        if hasattr(self.execution_result, "to_dict"):
            payload["execution_result"] = self.execution_result.to_dict()
        elif isinstance(self.execution_result, Mapping):
            payload["execution_result"] = dict(self.execution_result)
        else:
            payload["execution_result"] = _safe_repr(self.execution_result)
        return payload


class TradeManager:
    """Central AAQTS trade pipeline.

    Dependencies are optional at construction time so the class remains easy to
    unit-test. Live execution requires ``risk_manager`` and ``executor``.
    """

    def __init__(
        self,
        risk_manager: Any = None,
        executor: Any = None,
        position_manager: Any = None,
        decision_analyzer: Any = None,
        trade_quality: Any = None,
        config: Optional[TradeManagerConfig] = None,
        logger: Optional[logging.Logger] = None,
        news_filter: Optional[Callable[[TradeRequest], Any]] = None,
        exposure_filter: Optional[Callable[[TradeRequest, Sequence[Any]], Any]] = None,
    ) -> None:
        self.risk_manager = risk_manager
        self.executor = executor
        self.position_manager = position_manager
        self.decision_analyzer = decision_analyzer
        self.trade_quality = trade_quality
        self.config = config or TradeManagerConfig()
        self.logger = logger or logging.getLogger(__name__)
        self.news_filter = news_filter
        self.exposure_filter = exposure_filter

        self._lock = threading.RLock()
        self._inflight: set[str] = set()
        self._recent_fingerprints: dict[str, float] = {}
        self._last_trade_by_symbol: dict[str, float] = {}
        self._history: list[TradeOutcome] = []
        self._counters: MutableMapping[str, int] = {
            "received": 0,
            "approved": 0,
            "rejected": 0,
            "executed": 0,
            "failed": 0,
            "duplicates": 0,
        }

    # ------------------------------------------------------------------
    # Backward-compatible API
    # ------------------------------------------------------------------
    def calculate_trade(self, data: Any, signal: Any) -> dict[str, Any]:
        """Preserve the original two-field helper API."""
        current_price = _last_numeric(data, ("close", "Close"), required=True)
        atr = _last_numeric(data, ("ATR", "atr"), required=True)
        return {
            "current_price": current_price,
            "atr": atr,
        }

    def process_signal(
        self,
        data: Any,
        signal: Any,
        *,
        symbol: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        execute: bool = True,
    ) -> TradeOutcome:
        request = self.build_request(data, signal, symbol=symbol, context=context)
        return self.process_request(request, execute=execute)

    def build_request(
        self,
        data: Any,
        signal: Any,
        *,
        symbol: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> TradeRequest:
        context_dict = dict(context or {})
        resolved_symbol = str(
            symbol
            or context_dict.pop("symbol", None)
            or self.config.default_symbol
            or ""
        ).upper().strip()
        if not resolved_symbol:
            raise ValueError("symbol is required")

        timestamp = context_dict.pop("timestamp", None)
        if timestamp is None:
            timestamp = _index_timestamp(data) or datetime.now(timezone.utc)
        timestamp = _ensure_utc(timestamp)

        return TradeRequest(
            symbol=resolved_symbol,
            signal=normalize_signal(signal).value,
            entry_price=float(context_dict.pop("entry_price", _last_numeric(data, ("close", "Close"), True))),
            atr=float(context_dict.pop("atr", _last_numeric(data, ("ATR", "atr"), True))),
            timestamp=timestamp,
            confidence=float(context_dict.pop("confidence", _signal_value(signal, "confidence", 100.0))),
            quality_score=_optional_float(context_dict.pop("quality_score", _signal_value(signal, "quality_score", None))),
            timeframe=context_dict.pop("timeframe", None),
            strategy=context_dict.pop("strategy", _signal_value(signal, "strategy", None)),
            spread_points=_optional_float(context_dict.pop("spread_points", None)),
            slippage_points=_optional_float(context_dict.pop("slippage_points", None)),
            account_balance=_optional_float(context_dict.pop("account_balance", None)),
            account_equity=_optional_float(context_dict.pop("account_equity", None)),
            daily_profit_loss=float(context_dict.pop("daily_profit_loss", 0.0)),
            consecutive_losses=int(context_dict.pop("consecutive_losses", 0)),
            risk_multiplier=float(context_dict.pop("risk_multiplier", 1.0)),
            stop_loss=_optional_float(context_dict.pop("stop_loss", None)),
            take_profit=_optional_float(context_dict.pop("take_profit", None)),
            volume=_optional_float(context_dict.pop("volume", None)),
            metadata=context_dict,
        )

    def process_request(self, request: TradeRequest, *, execute: bool = True) -> TradeOutcome:
        self._increment("received")
        fingerprint = request.fingerprint()

        with self._lock:
            self._prune_recent()
            if fingerprint in self._inflight or self._is_recent_duplicate(fingerprint):
                decision = self._reject(request, "Duplicate signal blocked", TradeStatus.DUPLICATE)
                outcome = TradeOutcome(False, TradeStatus.DUPLICATE, decision)
                self._increment("duplicates")
                self._record(outcome)
                return outcome
            self._inflight.add(fingerprint)

        try:
            decision = self.evaluate_request(request)
            if not decision.approved:
                outcome = TradeOutcome(False, decision.status, decision)
                self._record(outcome)
                return outcome

            if not execute or self.config.dry_run:
                outcome = TradeOutcome(True, TradeStatus.APPROVED, decision)
                self._record(outcome)
                return outcome

            outcome = self.execute_decision(decision)
            self._record(outcome)
            return outcome
        except Exception as exc:
            self.logger.exception("Trade pipeline failed for %s", request.symbol)
            decision = self._reject(request, f"Internal trade-manager error: {exc}")
            outcome = TradeOutcome(False, TradeStatus.FAILED, decision, error=str(exc))
            self._increment("failed")
            self._record(outcome)
            if self.config.raise_on_internal_error:
                raise
            return outcome
        finally:
            with self._lock:
                self._inflight.discard(fingerprint)
                self._recent_fingerprints[fingerprint] = time_module.monotonic()

    # ------------------------------------------------------------------
    # Evaluation pipeline
    # ------------------------------------------------------------------
    def evaluate_request(self, request: TradeRequest) -> TradeDecision:
        reasons: list[str] = []
        warnings: list[str] = []

        self._validate_basic(request, reasons)
        positions = self._open_positions()
        self._validate_session(request, reasons)
        self._validate_spread(request, reasons)
        self._validate_slippage(request, reasons)
        self._validate_cooldown(request, reasons)
        self._validate_position_limits(request, positions, reasons)
        self._validate_correlation(request, positions, reasons)
        self._validate_news(request, reasons, warnings)
        self._validate_external_exposure(request, positions, reasons, warnings)
        self._apply_decision_analyzer(request, reasons, warnings)
        self._apply_trade_quality(request, reasons, warnings)

        if reasons:
            return self._reject(request, *reasons, warnings=warnings)

        risk = self._evaluate_risk(request, len(positions))
        risk_dict = _as_dict(risk)
        approved = bool(risk_dict.get("approved", risk_dict.get("allowed", True)))
        risk_reasons = _to_string_list(risk_dict.get("reasons", risk_dict.get("reason")))
        warnings.extend(_to_string_list(risk_dict.get("warnings")))
        if not approved:
            return self._reject(request, *(risk_reasons or ["RiskManager rejected trade"]), warnings=warnings)

        stop_loss = _first_float(
            request.stop_loss,
            risk_dict.get("stop_loss"),
            risk_dict.get("sl"),
            _nested(risk_dict, "levels", "stop_loss"),
        )
        take_profit = _first_float(
            request.take_profit,
            risk_dict.get("take_profit"),
            risk_dict.get("tp"),
            _nested(risk_dict, "levels", "take_profit"),
        )
        volume = _first_float(
            request.volume,
            risk_dict.get("volume"),
            risk_dict.get("lot_size"),
            risk_dict.get("position_size"),
        )

        final_reasons: list[str] = []
        if self.config.require_stop_loss and not _positive(stop_loss):
            final_reasons.append("Valid stop-loss was not produced")
        if self.config.require_take_profit and not _positive(take_profit):
            final_reasons.append("Valid take-profit was not produced")
        if not _positive(volume):
            final_reasons.append("Valid trade volume was not produced")
        if final_reasons:
            return self._reject(request, *final_reasons, warnings=warnings)

        decision = TradeDecision(
            approved=True,
            status=TradeStatus.APPROVED,
            request=request,
            warnings=warnings,
            risk=risk_dict,
            stop_loss=stop_loss,
            take_profit=take_profit,
            volume=volume,
        )
        self._increment("approved")
        return decision

    def _validate_basic(self, request: TradeRequest, reasons: list[str]) -> None:
        if not self.config.enabled:
            reasons.append("Trading is disabled")
        side = request.normalized_side()
        if side is TradeSide.HOLD:
            reasons.append("HOLD signal does not request a trade")
        elif side is TradeSide.BUY and not self.config.allow_buy:
            reasons.append("BUY trades are disabled")
        elif side is TradeSide.SELL and not self.config.allow_sell:
            reasons.append("SELL trades are disabled")
        if not request.symbol:
            reasons.append("Symbol is missing")
        if not _positive(request.entry_price):
            reasons.append("Entry price must be positive")
        if not _positive(request.atr):
            reasons.append("ATR must be positive")
        if request.confidence < self.config.minimum_signal_confidence:
            reasons.append(
                f"Signal confidence {request.confidence:.2f} is below "
                f"minimum {self.config.minimum_signal_confidence:.2f}"
            )
        if request.quality_score is not None and request.quality_score < self.config.minimum_trade_quality:
            reasons.append(
                f"Trade quality {request.quality_score:.2f} is below "
                f"minimum {self.config.minimum_trade_quality:.2f}"
            )

    def _validate_session(self, request: TradeRequest, reasons: list[str]) -> None:
        if not self.config.session_filter_enabled:
            return
        session = self.current_session(request.timestamp)
        if session not in {s.upper() for s in self.config.allowed_sessions}:
            reasons.append(f"Session {session} is not allowed")

    def _validate_spread(self, request: TradeRequest, reasons: list[str]) -> None:
        limit = self.config.maximum_spread_points
        if limit is not None and request.spread_points is not None and request.spread_points > limit:
            reasons.append(f"Spread {request.spread_points:.2f} exceeds maximum {limit:.2f} points")

    def _validate_slippage(self, request: TradeRequest, reasons: list[str]) -> None:
        limit = self.config.maximum_slippage_points
        if limit is not None and request.slippage_points is not None and request.slippage_points > limit:
            reasons.append(f"Slippage {request.slippage_points:.2f} exceeds maximum {limit:.2f} points")

    def _validate_cooldown(self, request: TradeRequest, reasons: list[str]) -> None:
        if self.config.cooldown_seconds <= 0:
            return
        previous = self._last_trade_by_symbol.get(request.symbol)
        if previous is None:
            return
        remaining = self.config.cooldown_seconds - (time_module.monotonic() - previous)
        if remaining > 0:
            reasons.append(f"Symbol cooldown active for another {math.ceil(remaining)} seconds")

    def _validate_position_limits(self, request: TradeRequest, positions: Sequence[Any], reasons: list[str]) -> None:
        if len(positions) >= self.config.maximum_open_positions:
            reasons.append("Maximum total open-position limit reached")
        symbol_positions = [p for p in positions if _position_symbol(p) == request.symbol]
        if len(symbol_positions) >= self.config.maximum_positions_per_symbol:
            reasons.append(f"Maximum positions for {request.symbol} reached")
        side = request.normalized_side().value
        position_sides = {_position_side(p) for p in symbol_positions}
        if self.config.one_direction_per_symbol and side in position_sides:
            reasons.append(f"Existing {side} position already open for {request.symbol}")
        opposite = TradeSide.SELL.value if side == TradeSide.BUY.value else TradeSide.BUY.value
        if self.config.block_opposite_direction and opposite in position_sides:
            reasons.append(f"Opposite {opposite} position already open for {request.symbol}")

    def _validate_correlation(self, request: TradeRequest, positions: Sequence[Any], reasons: list[str]) -> None:
        symbol = request.symbol
        for group in self.config.symbol_correlation_groups:
            normalized = {s.upper() for s in group}
            if symbol not in normalized:
                continue
            count = sum(1 for p in positions if _position_symbol(p) in normalized)
            if count >= self.config.maximum_correlated_positions:
                reasons.append(f"Correlated exposure limit reached for group containing {symbol}")
            return

    def _validate_news(self, request: TradeRequest, reasons: list[str], warnings: list[str]) -> None:
        if self.news_filter is None:
            return
        self._consume_filter_result(self.news_filter(request), "News filter", reasons, warnings)

    def _validate_external_exposure(
        self, request: TradeRequest, positions: Sequence[Any], reasons: list[str], warnings: list[str]
    ) -> None:
        if self.exposure_filter is None:
            return
        self._consume_filter_result(self.exposure_filter(request, positions), "Exposure filter", reasons, warnings)

    def _apply_decision_analyzer(self, request: TradeRequest, reasons: list[str], warnings: list[str]) -> None:
        if self.decision_analyzer is None:
            return
        method = _first_callable(self.decision_analyzer, ("analyze", "evaluate", "analyze_trade"))
        if method is None:
            warnings.append("DecisionAnalyzer has no supported evaluation method")
            return
        result = _invoke_flexible(method, request=request, trade_request=request, signal=request.signal, context=request.metadata)
        self._consume_filter_result(result, "Decision analyzer", reasons, warnings)

    def _apply_trade_quality(self, request: TradeRequest, reasons: list[str], warnings: list[str]) -> None:
        if self.trade_quality is None:
            return
        method = _first_callable(self.trade_quality, ("evaluate", "score", "calculate", "analyze"))
        if method is None:
            warnings.append("TradeQuality has no supported scoring method")
            return
        result = _invoke_flexible(method, request=request, trade_request=request, signal=request.signal, context=request.metadata)
        data = _as_dict(result)
        score = _first_float(data.get("score"), data.get("quality_score"), result if isinstance(result, (int, float)) else None)
        if score is not None:
            request.quality_score = score
            if score < self.config.minimum_trade_quality:
                reasons.append(f"Trade quality {score:.2f} is below minimum {self.config.minimum_trade_quality:.2f}")
        self._consume_filter_result(result, "Trade quality", reasons, warnings, consume_score=False)

    def _evaluate_risk(self, request: TradeRequest, open_trades: int) -> Any:
        if self.risk_manager is None:
            raise RuntimeError("RiskManager is required")
        account = self._account_snapshot(request)
        info = self._symbol_info(request.symbol)
        kwargs = {
            "signal": request.normalized_side().value,
            "account_balance": request.account_balance or account.get("balance"),
            "account_equity": request.account_equity or account.get("equity"),
            "entry_price": request.entry_price,
            "atr": request.atr,
            "risk_multiplier": request.risk_multiplier,
            "daily_profit_loss": request.daily_profit_loss,
            "open_trades": open_trades,
            "consecutive_losses": request.consecutive_losses,
            "spread_points": request.spread_points,
            "tick_size": _attr_or_key(info, "trade_tick_size", "tick_size"),
            "tick_value": _attr_or_key(info, "trade_tick_value", "tick_value"),
            "minimum_lot": _attr_or_key(info, "volume_min"),
            "maximum_lot": _attr_or_key(info, "volume_max"),
            "lot_step": _attr_or_key(info, "volume_step"),
            "price_digits": int(_attr_or_key(info, "digits") or 5),
        }
        if not _positive(kwargs["account_balance"]):
            raise RuntimeError("Account balance is unavailable or invalid")
        method = getattr(self.risk_manager, "evaluate_trade", None)
        if callable(method):
            return _invoke_supported_kwargs(method, kwargs)
        levels = self.risk_manager.calculate_trade_levels(
            request.normalized_side().value, request.entry_price, request.atr
        )
        levels_dict = _as_dict(levels)
        stop_loss = _first_float(levels_dict.get("stop_loss"), levels_dict.get("sl"))
        volume = request.volume
        if volume is None and callable(getattr(self.risk_manager, "position_size", None)):
            volume = self.risk_manager.position_size(kwargs["account_balance"], request.entry_price, stop_loss)
        return {"approved": True, **levels_dict, "volume": volume}

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute_decision(self, decision: TradeDecision) -> TradeOutcome:
        if not decision.approved:
            return TradeOutcome(False, TradeStatus.REJECTED, decision)
        if self.executor is None:
            return TradeOutcome(False, TradeStatus.FAILED, decision, error="MT5Executor is required")

        request = decision.request
        comment = self._comment(request)
        result = self.executor.place_market_order(
            symbol=request.symbol,
            side=request.normalized_side().value,
            volume=float(decision.volume),
            stop_loss=float(decision.stop_loss),
            take_profit=float(decision.take_profit),
            comment=comment,
        )
        result_dict = _as_dict(result)
        success = bool(result_dict.get("success", getattr(result, "success", False)))
        ticket = _first_int(
            result_dict.get("position"),
            result_dict.get("position_ticket"),
            result_dict.get("order"),
            getattr(result, "position", None),
            getattr(result, "order", None),
        )

        if not success:
            error = str(
                result_dict.get("error")
                or result_dict.get("message")
                or result_dict.get("comment")
                or "Order execution failed"
            )
            self._increment("failed")
            return TradeOutcome(False, TradeStatus.FAILED, decision, result, ticket, error)

        if self.position_manager is not None:
            try:
                register = getattr(self.position_manager, "register_execution_result", None)
                if callable(register):
                    register(result)
                elif ticket is not None:
                    broker_position = self._fetch_position(ticket)
                    if broker_position is not None:
                        self.position_manager.register_position(broker_position)
            except Exception as exc:
                self.logger.exception("Position registration failed for ticket %s", ticket)
                decision.warnings.append(f"Execution succeeded but position registration failed: {exc}")

        with self._lock:
            self._last_trade_by_symbol[request.symbol] = time_module.monotonic()
        self._increment("executed")
        return TradeOutcome(True, TradeStatus.EXECUTED, decision, result, ticket)

    # ------------------------------------------------------------------
    # Broker and state helpers
    # ------------------------------------------------------------------
    def _account_snapshot(self, request: TradeRequest) -> dict[str, Any]:
        if request.account_balance is not None:
            return {"balance": request.account_balance, "equity": request.account_equity or request.account_balance}
        if self.executor is None or not callable(getattr(self.executor, "account_info", None)):
            return {}
        return _as_dict(self.executor.account_info())

    def _symbol_info(self, symbol: str) -> Any:
        if self.executor is None or not callable(getattr(self.executor, "symbol_info", None)):
            return None
        try:
            return self.executor.symbol_info(symbol)
        except Exception:
            self.logger.exception("Could not obtain symbol info for %s", symbol)
            return None

    def _open_positions(self) -> list[Any]:
        try:
            if self.position_manager is not None:
                method = _first_callable(self.position_manager, ("all_positions", "positions"))
                if method is not None:
                    positions = method()
                    return [p for p in (positions or []) if _position_is_open(p)]
            if self.executor is not None and callable(getattr(self.executor, "positions", None)):
                return list(self.executor.positions(managed_only=True) or [])
        except Exception:
            self.logger.exception("Open-position retrieval failed")
            if self.config.fail_closed:
                raise
        return []

    def _fetch_position(self, ticket: int) -> Any:
        if self.executor is None:
            return None
        method = getattr(self.executor, "_position_by_ticket", None)
        if callable(method):
            return method(ticket)
        positions = self.executor.positions(managed_only=False)
        for position in positions or []:
            if _first_int(_attr_or_key(position, "ticket")) == ticket:
                return position
        return None

    # ------------------------------------------------------------------
    # Reporting and maintenance
    # ------------------------------------------------------------------
    def current_session(self, timestamp: Optional[datetime] = None) -> str:
        timestamp = _ensure_utc(timestamp or datetime.now(timezone.utc))
        hour = timestamp.hour
        sessions = self.config.utc_session_hours
        overlap = sessions.get("OVERLAP")
        if overlap and _hour_in_range(hour, *overlap):
            return "OVERLAP"
        for name in ("LONDON", "NEW_YORK", "ASIA"):
            bounds = sessions.get(name)
            if bounds and _hour_in_range(hour, *bounds):
                return name
        return "OFF_HOURS"

    def history(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        with self._lock:
            items = self._history[-limit:] if limit else list(self._history)
        return [item.to_dict() for item in items]

    def statistics(self) -> dict[str, Any]:
        with self._lock:
            counters = dict(self._counters)
            total = counters["received"]
            counters["approval_rate"] = counters["approved"] / total if total else 0.0
            counters["execution_rate"] = counters["executed"] / total if total else 0.0
            counters["history_size"] = len(self._history)
            counters["inflight"] = len(self._inflight)
            return counters

    def reset_runtime_state(self, *, clear_history: bool = False) -> None:
        with self._lock:
            self._inflight.clear()
            self._recent_fingerprints.clear()
            self._last_trade_by_symbol.clear()
            if clear_history:
                self._history.clear()

    def health_report(self) -> dict[str, Any]:
        return {
            "healthy": bool(self.config.enabled and self.risk_manager is not None and self.executor is not None),
            "enabled": self.config.enabled,
            "dry_run": self.config.dry_run,
            "risk_manager": self.risk_manager is not None,
            "executor": self.executor is not None,
            "position_manager": self.position_manager is not None,
            "decision_analyzer": self.decision_analyzer is not None,
            "trade_quality": self.trade_quality is not None,
            "statistics": self.statistics(),
            "session": self.current_session(),
        }

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------
    def _reject(
        self,
        request: TradeRequest,
        *reasons: str,
        warnings: Optional[Iterable[str]] = None,
        status: TradeStatus = TradeStatus.REJECTED,
    ) -> TradeDecision:
        self._increment("rejected")
        return TradeDecision(
            approved=False,
            status=status,
            request=request,
            reasons=[str(r) for r in reasons if str(r).strip()],
            warnings=list(warnings or []),
        )

    def _consume_filter_result(
        self,
        result: Any,
        label: str,
        reasons: list[str],
        warnings: list[str],
        *,
        consume_score: bool = True,
    ) -> None:
        if result is None:
            return
        if isinstance(result, bool):
            if not result:
                reasons.append(f"{label} rejected trade")
            return
        data = _as_dict(result)
        approved = data.get("approved", data.get("allowed", data.get("pass", True)))
        if approved is False:
            messages = _to_string_list(data.get("reasons", data.get("reason")))
            reasons.extend(messages or [f"{label} rejected trade"])
        warnings.extend(_to_string_list(data.get("warnings")))

    def _comment(self, request: TradeRequest) -> str:
        parts = [self.config.comment_prefix, request.strategy or request.timeframe or "TRADE"]
        return "|".join(parts)[:31]

    def _record(self, outcome: TradeOutcome) -> None:
        with self._lock:
            self._history.append(outcome)

    def _increment(self, name: str) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + 1

    def _is_recent_duplicate(self, fingerprint: str) -> bool:
        previous = self._recent_fingerprints.get(fingerprint)
        return previous is not None and (time_module.monotonic() - previous) < self.config.duplicate_window_seconds

    def _prune_recent(self) -> None:
        if self.config.duplicate_window_seconds <= 0:
            self._recent_fingerprints.clear()
            return
        cutoff = time_module.monotonic() - self.config.duplicate_window_seconds
        stale = [key for key, seen_at in self._recent_fingerprints.items() if seen_at < cutoff]
        for key in stale:
            self._recent_fingerprints.pop(key, None)


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------
def normalize_signal(signal: Any) -> TradeSide:
    if isinstance(signal, TradeSide):
        return signal
    if isinstance(signal, Mapping):
        signal = signal.get("signal", signal.get("side", signal.get("action", "HOLD")))
    elif not isinstance(signal, str):
        signal = getattr(signal, "signal", getattr(signal, "side", getattr(signal, "action", signal)))
    text = str(signal).strip().upper()
    aliases = {
        "LONG": TradeSide.BUY,
        "BULLISH": TradeSide.BUY,
        "1": TradeSide.BUY,
        "SHORT": TradeSide.SELL,
        "BEARISH": TradeSide.SELL,
        "-1": TradeSide.SELL,
        "NONE": TradeSide.HOLD,
        "NEUTRAL": TradeSide.HOLD,
        "0": TradeSide.HOLD,
        "": TradeSide.HOLD,
    }
    if text in TradeSide.__members__:
        return TradeSide[text]
    if text in aliases:
        return aliases[text]
    raise ValueError(f"Unsupported signal: {signal!r}")


def _last_numeric(data: Any, names: Sequence[str], required: bool = False) -> Optional[float]:
    for name in names:
        try:
            column = data[name]
            value = column.iloc[-1] if hasattr(column, "iloc") else column[-1]
            value = float(value)
            if math.isfinite(value):
                return value
        except Exception:
            continue
    if required:
        raise ValueError(f"Missing or invalid data column; expected one of {tuple(names)}")
    return None


def _index_timestamp(data: Any) -> Optional[datetime]:
    try:
        value = data.index[-1]
        if hasattr(value, "to_pydatetime"):
            value = value.to_pydatetime()
        return value if isinstance(value, datetime) else None
    except Exception:
        return None


def _signal_value(signal: Any, name: str, default: Any) -> Any:
    if isinstance(signal, Mapping):
        return signal.get(name, default)
    return getattr(signal, name, default)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            result = value.to_dict()
            return dict(result) if isinstance(result, Mapping) else {}
        except Exception:
            return {}
    try:
        return asdict(value)
    except Exception:
        result: dict[str, Any] = {}
        for name in dir(value):
            if name.startswith("_"):
                continue
            try:
                item = getattr(value, name)
            except Exception:
                continue
            if not callable(item):
                result[name] = item
        return result


def _invoke_supported_kwargs(method: Callable[..., Any], kwargs: Mapping[str, Any]) -> Any:
    signature = inspect.signature(method)
    supports_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
    filtered = dict(kwargs) if supports_var_kw else {k: v for k, v in kwargs.items() if k in signature.parameters}
    return method(**filtered)


def _invoke_flexible(method: Callable[..., Any], **kwargs: Any) -> Any:
    try:
        return _invoke_supported_kwargs(method, kwargs)
    except TypeError:
        request = kwargs.get("request")
        try:
            return method(request)
        except TypeError:
            return method()


def _first_callable(obj: Any, names: Sequence[str]) -> Optional[Callable[..., Any]]:
    for name in names:
        method = getattr(obj, name, None)
        if callable(method):
            return method
    return None


def _attr_or_key(value: Any, *names: str) -> Any:
    if value is None:
        return None
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        try:
            result = getattr(value, name)
            if result is not None:
                return result
        except Exception:
            pass
    return None


def _position_symbol(position: Any) -> str:
    return str(_attr_or_key(position, "symbol") or "").upper()


def _position_side(position: Any) -> str:
    raw = _attr_or_key(position, "side", "direction", "type")
    if isinstance(raw, int):
        return TradeSide.BUY.value if raw == 0 else TradeSide.SELL.value
    try:
        return normalize_signal(raw).value
    except Exception:
        return str(raw or "").upper()


def _position_is_open(position: Any) -> bool:
    is_open = _attr_or_key(position, "is_open")
    if callable(is_open):
        try:
            return bool(is_open())
        except Exception:
            return True
    if is_open is not None:
        return bool(is_open)
    state = str(_attr_or_key(position, "state", "status") or "OPEN").upper()
    return state not in {"CLOSED", "REMOVED", "FAILED"}


def _to_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return [str(item) for item in value]
    return [str(value)]


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _first_float(*values: Any) -> Optional[float]:
    for value in values:
        result = _optional_float(value)
        if result is not None:
            return result
    return None


def _first_int(*values: Any) -> Optional[int]:
    for value in values:
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
    return None


def _positive(value: Any) -> bool:
    result = _optional_float(value)
    return result is not None and result > 0


def _nested(mapping: Mapping[str, Any], outer: str, inner: str) -> Any:
    value = mapping.get(outer)
    return value.get(inner) if isinstance(value, Mapping) else None


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hour_in_range(hour: int, start: int, end: int) -> bool:
    return start <= hour < end if start <= end else hour >= start or hour < end


def _safe_repr(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return repr(value)


__all__ = [
    "TradeManager",
    "TradeManagerConfig",
    "TradeRequest",
    "TradeDecision",
    "TradeOutcome",
    "TradeSide",
    "TradeStatus",
    "normalize_signal",
]
