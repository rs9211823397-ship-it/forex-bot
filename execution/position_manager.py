from __future__ import annotations

import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


###############################################################################
# MODULE CONSTANTS
###############################################################################

POSITION_MANAGER_VERSION = "2.1.0"

EPSILON = 1e-9


###############################################################################
# POSITION STATES
###############################################################################

class PositionState(str, Enum):
    """
    Current lifecycle state of an AAQTS-managed position.
    """

    PENDING = "PENDING"
    OPEN = "OPEN"
    BREAK_EVEN = "BREAK_EVEN"
    TP1 = "TP1"
    TP2 = "TP2"
    RUNNER = "RUNNER"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


###############################################################################
# EXIT REASONS
###############################################################################

class ExitReason(str, Enum):
    """
    Standardized reasons for removing or closing a managed position.
    """

    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    BREAK_EVEN = "BREAK_EVEN"
    TP1_PARTIAL = "TP1_PARTIAL"
    TP2_PARTIAL = "TP2_PARTIAL"
    TIME_EXIT = "TIME_EXIT"
    SESSION_CLOSE = "SESSION_CLOSE"
    NEWS_EXIT = "NEWS_EXIT"
    RISK_EXIT = "RISK_EXIT"
    MANUAL = "MANUAL"
    BROKER_CLOSED = "BROKER_CLOSED"
    EMERGENCY = "EMERGENCY"
    UNKNOWN = "UNKNOWN"


###############################################################################
# POSITION MANAGER CONFIGURATION
###############################################################################

@dataclass(frozen=True)
class PositionManagerConfig:
    """
    Global configuration for position lifecycle management.

    The configuration is immutable after initialization to prevent accidental
    runtime changes to risk and exit rules.
    """

    # Synchronization
    sync_interval_seconds: float = 10.0
    position_refresh_seconds: float = 2.0

    # Break-even
    enable_break_even: bool = True
    break_even_trigger_rr: float = 1.0
    break_even_offset_points: float = 0.0

    # Trailing stop
    enable_trailing_stop: bool = True
    trailing_start_rr: float = 1.25
    trailing_atr_multiplier: float = 1.5
    minimum_trailing_distance_points: float = 0.0

    # TP1
    enable_tp1: bool = True
    tp1_trigger_rr: float = 1.0
    tp1_close_ratio: float = 0.50

    # TP2
    enable_tp2: bool = True
    tp2_trigger_rr: float = 2.0
    tp2_close_ratio: float = 0.30

    # Runner
    enable_runner: bool = True
    runner_after_tp2: bool = True

    # Time-based exit
    enable_time_exit: bool = True
    maximum_trade_minutes: int = 480

    # Safety
    require_initial_stop_loss: bool = True
    preserve_original_risk: bool = True
    remove_missing_broker_positions: bool = True
    raise_management_errors: bool = False

    # History and metadata
    maximum_closed_history: int = 1000
    record_event_history: bool = True

    def __post_init__(self) -> None:
        """
        Validate configuration values immediately.
        """

        if self.sync_interval_seconds < 0:
            raise ValueError(
                "sync_interval_seconds cannot be negative."
            )

        if self.position_refresh_seconds < 0:
            raise ValueError(
                "position_refresh_seconds cannot be negative."
            )

        if self.break_even_trigger_rr < 0:
            raise ValueError(
                "break_even_trigger_rr cannot be negative."
            )

        if self.trailing_start_rr < 0:
            raise ValueError(
                "trailing_start_rr cannot be negative."
            )

        if self.trailing_atr_multiplier <= 0:
            raise ValueError(
                "trailing_atr_multiplier must be greater than zero."
            )

        if self.tp1_trigger_rr <= 0:
            raise ValueError(
                "tp1_trigger_rr must be greater than zero."
            )

        if self.tp2_trigger_rr <= self.tp1_trigger_rr:
            raise ValueError(
                "tp2_trigger_rr must be greater than tp1_trigger_rr."
            )

        if not 0 < self.tp1_close_ratio < 1:
            raise ValueError(
                "tp1_close_ratio must be between 0 and 1."
            )

        if not 0 < self.tp2_close_ratio < 1:
            raise ValueError(
                "tp2_close_ratio must be between 0 and 1."
            )

        if self.maximum_trade_minutes <= 0:
            raise ValueError(
                "maximum_trade_minutes must be greater than zero."
            )

        if self.maximum_closed_history <= 0:
            raise ValueError(
                "maximum_closed_history must be greater than zero."
            )


###############################################################################
# POSITION EVENT
###############################################################################

@dataclass
class PositionEvent:
    """
    One lifecycle event recorded against a managed position.
    """

    event_type: str

    timestamp: float = field(
        default_factory=time.time
    )

    message: str = ""

    data: dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def timestamp_iso(self) -> str:
        """
        Return the event timestamp in UTC ISO format.
        """

        return datetime.fromtimestamp(
            self.timestamp,
            tz=timezone.utc,
        ).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """
        Convert the event into a serializable dictionary.
        """

        payload = asdict(self)

        payload["timestamp_iso"] = self.timestamp_iso

        return payload


###############################################################################
# MANAGED POSITION
###############################################################################

@dataclass
class ManagedPosition:
    """
    Internal AAQTS representation of an open MT5 position.

    The object preserves the original entry risk even when the stop loss later
    moves to break-even or begins trailing.
    """

    ticket: int
    position_id: str
    symbol: str
    side: str

    initial_volume: float
    current_volume: float

    entry_price: float
    initial_stop_loss: float
    current_stop_loss: float
    take_profit: float

    original_risk_per_unit: float
    opened_at: float

    state: PositionState = PositionState.OPEN

    break_even_done: bool = False
    tp1_done: bool = False
    tp2_done: bool = False
    trailing_active: bool = False

    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None

    current_price: Optional[float] = None
    floating_profit: float = 0.0
    current_rr: float = 0.0
    maximum_favorable_rr: float = 0.0
    maximum_adverse_rr: float = 0.0

    last_broker_sync: float = 0.0
    last_management_time: float = 0.0

    exit_reason: Optional[ExitReason] = None
    closed_at: Optional[float] = None

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    events: list[PositionEvent] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        """
        Normalize and validate position values.
        """

        self.ticket = int(self.ticket)

        self.symbol = str(
            self.symbol
        ).strip()

        self.side = str(
            self.side
        ).upper().strip()

        self.initial_volume = float(
            self.initial_volume
        )

        self.current_volume = float(
            self.current_volume
        )

        self.entry_price = float(
            self.entry_price
        )

        self.initial_stop_loss = float(
            self.initial_stop_loss
        )

        self.current_stop_loss = float(
            self.current_stop_loss
        )

        self.take_profit = float(
            self.take_profit
        )

        self.original_risk_per_unit = float(
            self.original_risk_per_unit
        )

        self.opened_at = float(
            self.opened_at
        )

        if not self.position_id:
            self.position_id = str(
                uuid.uuid4()
            )

        if not self.symbol:
            raise ValueError(
                "ManagedPosition symbol cannot be empty."
            )

        if self.side not in {"BUY", "SELL"}:
            raise ValueError(
                "ManagedPosition side must be BUY or SELL."
            )

        if self.ticket <= 0:
            raise ValueError(
                "ManagedPosition ticket must be greater than zero."
            )

        if self.initial_volume <= 0:
            raise ValueError(
                "Initial position volume must be greater than zero."
            )

        if self.current_volume <= 0:
            raise ValueError(
                "Current position volume must be greater than zero."
            )

        if self.entry_price <= 0:
            raise ValueError(
                "Entry price must be greater than zero."
            )

        if self.opened_at <= 0:
            raise ValueError(
                "Position opening time must be greater than zero."
            )

        if self.original_risk_per_unit < 0:
            raise ValueError(
                "Original risk per unit cannot be negative."
            )

        if self.highest_price is None:
            self.highest_price = self.entry_price

        if self.lowest_price is None:
            self.lowest_price = self.entry_price

        if self.current_price is None:
            self.current_price = self.entry_price

    @property
    def age_seconds(self) -> float:
        """
        Return the current age of the position in seconds.
        """

        reference_time = (
            self.closed_at
            if self.closed_at is not None
            else time.time()
        )

        return max(
            0.0,
            reference_time - self.opened_at,
        )

    @property
    def age_minutes(self) -> float:
        """
        Return the current age of the position in minutes.
        """

        return self.age_seconds / 60.0

    @property
    def age_hours(self) -> float:
        """
        Return the current age of the position in hours.
        """

        return self.age_minutes / 60.0

    @property
    def is_open(self) -> bool:
        """
        Return whether the position is still considered active.
        """

        return self.state not in {
            PositionState.CLOSED,
            PositionState.ERROR,
        }

    @property
    def is_buy(self) -> bool:
        """
        Return whether this is a BUY position.
        """

        return self.side == "BUY"

    @property
    def is_sell(self) -> bool:
        """
        Return whether this is a SELL position.
        """

        return self.side == "SELL"

    @property
    def remaining_volume_ratio(self) -> float:
        """
        Return current volume as a fraction of initial volume.
        """

        if self.initial_volume <= EPSILON:
            return 0.0

        return max(
            0.0,
            self.current_volume / self.initial_volume,
        )

    @property
    def closed_volume(self) -> float:
        """
        Return the volume already closed.
        """

        return max(
            0.0,
            self.initial_volume - self.current_volume,
        )

    @property
    def has_valid_original_risk(self) -> bool:
        """
        Return whether the position has a usable original risk distance.
        """

        return self.original_risk_per_unit > EPSILON

    def add_event(
        self,
        event_type: str,
        message: str = "",
        **data: Any,
    ) -> PositionEvent:
        """
        Add a lifecycle event to the position.
        """

        event = PositionEvent(
            event_type=str(event_type),
            message=str(message),
            data=dict(data),
        )

        self.events.append(event)

        return event

    def update_price_extremes(
        self,
        price: float,
    ) -> None:
        """
        Update highest and lowest observed prices.
        """

        price = float(price)

        if not math.isfinite(price) or price <= 0:
            return

        self.current_price = price

        if (
            self.highest_price is None
            or price > self.highest_price
        ):
            self.highest_price = price

        if (
            self.lowest_price is None
            or price < self.lowest_price
        ):
            self.lowest_price = price

    def to_dict(
        self,
        include_events: bool = True,
    ) -> dict[str, Any]:
        """
        Convert the managed position into a serializable dictionary.
        """

        payload = asdict(self)

        payload["state"] = self.state.value

        payload["exit_reason"] = (
            self.exit_reason.value
            if self.exit_reason is not None
            else None
        )

        payload["opened_at_iso"] = datetime.fromtimestamp(
            self.opened_at,
            tz=timezone.utc,
        ).isoformat()

        payload["closed_at_iso"] = (
            datetime.fromtimestamp(
                self.closed_at,
                tz=timezone.utc,
            ).isoformat()
            if self.closed_at is not None
            else None
        )

        payload["age_seconds"] = self.age_seconds
        payload["age_minutes"] = self.age_minutes
        payload["remaining_volume_ratio"] = (
            self.remaining_volume_ratio
        )
        payload["closed_volume"] = self.closed_volume

        if include_events:
            payload["events"] = [
                event.to_dict()
                for event in self.events
            ]
        else:
            payload.pop(
                "events",
                None,
            )

        return payload


###############################################################################
# POSITION MANAGER STATISTICS
###############################################################################

@dataclass
class PositionStatistics:
    """
    Runtime statistics for position-management activity.
    """

    registered: int = 0
    recovered: int = 0
    synchronized: int = 0
    refreshed: int = 0

    closed: int = 0
    broker_closed: int = 0
    manual_closed: int = 0

    break_even_updates: int = 0
    trailing_updates: int = 0

    tp1_executions: int = 0
    tp2_executions: int = 0
    partial_closes: int = 0
    runner_positions: int = 0

    time_exits: int = 0
    session_exits: int = 0
    news_exits: int = 0
    emergency_exits: int = 0

    synchronization_errors: int = 0
    management_errors: int = 0
    execution_errors: int = 0

    last_sync_time: Optional[float] = None
    last_management_time: Optional[float] = None

    def increment(
        self,
        field_name: str,
        amount: int = 1,
    ) -> None:
        """
        Safely increment an integer statistics field.
        """

        if not hasattr(
            self,
            field_name,
        ):
            raise AttributeError(
                f"Unknown statistics field: {field_name}"
            )

        current_value = getattr(
            self,
            field_name,
        )

        if not isinstance(
            current_value,
            int,
        ):
            raise TypeError(
                f"{field_name} is not an integer counter."
            )

        setattr(
            self,
            field_name,
            current_value + int(amount),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        Convert statistics into a serializable dictionary.
        """

        payload = asdict(self)

        payload["last_sync_time_iso"] = (
            datetime.fromtimestamp(
                self.last_sync_time,
                tz=timezone.utc,
            ).isoformat()
            if self.last_sync_time is not None
            else None
        )

        payload["last_management_time_iso"] = (
            datetime.fromtimestamp(
                self.last_management_time,
                tz=timezone.utc,
            ).isoformat()
            if self.last_management_time is not None
            else None
        )

        return payload

###############################################################################
# POSITION MANAGER
###############################################################################

class PositionManager:
    """
    Production-grade position lifecycle manager.

    Responsibilities
    ----------------
    • Position registry
    • Position synchronization
    • Break-even management
    • Trailing stop management
    • TP1 / TP2 automation
    • Position analytics
    • Recovery after restart
    """

    def __init__(
        self,
        executor,
        config: Optional[
            PositionManagerConfig
        ] = None,
    ):

        self.executor = executor

        self.config = (
            config
            or PositionManagerConfig()
        )

        ####################################################################
        # ACTIVE POSITIONS
        ####################################################################

        self.positions: dict[
            int,
            ManagedPosition,
        ] = {}

        ####################################################################
        # CLOSED HISTORY
        ####################################################################

        self.closed_positions: list[
            ManagedPosition
        ] = []

        ####################################################################
        # RUNTIME
        ####################################################################

        self.statistics = (
            PositionStatistics()
        )

        self.last_sync = 0.0

        self.last_management_cycle = 0.0

    ###########################################################################
    # REGISTRATION
    ###########################################################################

    def register_position(
        self,
        mt5_position,
    ) -> ManagedPosition:

        ticket = int(
            mt5_position.ticket
        )

        existing = self.positions.get(
            ticket
        )

        if existing is not None:
            return existing

        side = (
            "BUY"
            if (
                mt5_position.type
                == self.executor.mt5.POSITION_TYPE_BUY
            )
            else "SELL"
        )

        stop_loss = float(
            getattr(
                mt5_position,
                "sl",
                0.0,
            )
            or 0.0
        )

        take_profit = float(
            getattr(
                mt5_position,
                "tp",
                0.0,
            )
            or 0.0
        )

        entry = float(
            mt5_position.price_open
        )

        original_risk = (
            abs(entry - stop_loss)
            if stop_loss > 0
            else 0.0
        )

        position = ManagedPosition(

            ticket=ticket,

            position_id=str(
                uuid.uuid4()
            ),

            symbol=mt5_position.symbol,

            side=side,

            initial_volume=float(
                mt5_position.volume
            ),

            current_volume=float(
                mt5_position.volume
            ),

            entry_price=entry,

            initial_stop_loss=stop_loss,

            current_stop_loss=stop_loss,

            take_profit=take_profit,

            original_risk_per_unit=original_risk,

            opened_at=float(
                getattr(
                    mt5_position,
                    "time",
                    time.time(),
                )
            ),

        )

        position.metadata[
            "magic"
        ] = getattr(
            mt5_position,
            "magic",
            None,
        )

        position.metadata[
            "comment"
        ] = getattr(
            mt5_position,
            "comment",
            "",
        )

        position.metadata[
            "registered_at"
        ] = time.time()

        position.add_event(

            "REGISTER",

            "Position registered.",

            ticket=ticket,

        )

        self.positions[
            ticket
        ] = position

        self.statistics.increment(
            "registered"
        )

        return position

    ###########################################################################
    # REMOVE
    ###########################################################################

    def remove_position(
        self,
        ticket: int,
        reason: ExitReason,
    ) -> bool:

        position = self.positions.pop(
            int(ticket),
            None,
        )

        if position is None:
            return False

        position.state = (
            PositionState.CLOSED
        )

        position.closed_at = (
            time.time()
        )

        position.exit_reason = reason

        position.add_event(

            "CLOSED",

            f"Closed ({reason.value})",

        )

        self.closed_positions.append(
            position
        )

        if (
            len(
                self.closed_positions
            )
            > self.config.maximum_closed_history
        ):

            self.closed_positions.pop(
                0
            )

        self.statistics.increment(
            "closed"
        )

        if (
            reason
            == ExitReason.BROKER_CLOSED
        ):

            self.statistics.increment(
                "broker_closed"
            )

        elif (
            reason
            == ExitReason.MANUAL
        ):

            self.statistics.increment(
                "manual_closed"
            )

        return True

    ###########################################################################
    # LOOKUP
    ###########################################################################

    def get(
        self,
        ticket: int,
    ) -> Optional[
        ManagedPosition
    ]:

        return self.positions.get(
            int(ticket)
        )

    def exists(
        self,
        ticket: int,
    ) -> bool:

        return (
            int(ticket)
            in self.positions
        )

    def all_positions(
        self,
    ) -> list[
        ManagedPosition
    ]:

        return list(
            self.positions.values()
        )

    ###########################################################################
    # COUNTS
    ###########################################################################

    @property
    def active_count(
        self,
    ) -> int:

        return len(
            self.positions
        )

    @property
    def closed_count(
        self,
    ) -> int:

        return len(
            self.closed_positions
        )

    ###########################################################################
    # CLEAR
    ###########################################################################

    def clear_registry(
        self,
        keep_history: bool = True,
    ) -> None:

        self.positions.clear()

        if not keep_history:

            self.closed_positions.clear()

    ###########################################################################
    # EXPORT
    ###########################################################################

    def statistics_dict(
        self,
    ) -> dict[str, Any]:

        return (
            self.statistics.to_dict()
        )

    def registry_snapshot(
        self,
    ) -> dict[int, dict]:

        return {

            ticket:
            position.to_dict(
                include_events=False
            )

            for ticket, position
            in self.positions.items()

        }

    ###########################################################################
    # SYNCHRONIZATION
    ###########################################################################

    def synchronize(
        self,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Synchronize the local registry with positions currently open in MT5.

        Returns a summary containing newly registered, updated, and removed
        position tickets.
        """

        now = time.time()

        if (
            not force
            and now - self.last_sync
            < self.config.sync_interval_seconds
        ):
            return {
                "synchronized": False,
                "reason": "sync_interval_not_reached",
                "registered": [],
                "updated": [],
                "removed": [],
                "active": self.active_count,
            }

        broker_positions = self.executor.positions(
            managed_only=True
        )

        broker_by_ticket = {
            int(position.ticket): position
            for position in broker_positions
        }

        registered: list[int] = []
        updated: list[int] = []
        removed: list[int] = []

        #######################################################################
        # REGISTER NEW AND UPDATE EXISTING POSITIONS
        #######################################################################

        for ticket, broker_position in broker_by_ticket.items():

            managed = self.positions.get(
                ticket
            )

            if managed is None:

                managed = self.register_position(
                    broker_position
                )

                registered.append(
                    ticket
                )

            else:

                self._update_from_broker(
                    managed,
                    broker_position,
                )

                updated.append(
                    ticket
                )

        #######################################################################
        # REMOVE POSITIONS NO LONGER OPEN AT BROKER
        #######################################################################

        if self.config.remove_missing_broker_positions:

            local_tickets = list(
                self.positions.keys()
            )

            for ticket in local_tickets:

                if ticket in broker_by_ticket:
                    continue

                removed_successfully = (
                    self.remove_position(
                        ticket,
                        ExitReason.BROKER_CLOSED,
                    )
                )

                if removed_successfully:

                    removed.append(
                        ticket
                    )

        self.last_sync = now

        self.statistics.increment(
            "synchronized"
        )

        self.statistics.last_sync_time = now

        return {
            "synchronized": True,
            "registered": registered,
            "updated": updated,
            "removed": removed,
            "active": self.active_count,
        }

    ###########################################################################
    # SAFE SYNCHRONIZATION
    ###########################################################################

    def safe_synchronize(
        self,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Synchronize without allowing an MT5 exception to terminate the main
        position-management loop.
        """

        try:

            return self.synchronize(
                force=force
            )

        except Exception as exc:

            self.statistics.increment(
                "synchronization_errors"
            )

            if self.config.raise_management_errors:
                raise

            return {
                "synchronized": False,
                "reason": "synchronization_error",
                "error": str(exc),
                "registered": [],
                "updated": [],
                "removed": [],
                "active": self.active_count,
            }

    ###########################################################################
    # POSITION RECOVERY
    ###########################################################################

    def recover_positions(
        self,
        reset_registry: bool = False,
    ) -> list[ManagedPosition]:
        """
        Recover all currently open AAQTS positions from MT5.

        This method should be called after:

        • Application startup
        • MT5 reconnection
        • Terminal restart
        • Network recovery
        """

        if reset_registry:

            self.positions.clear()

        broker_positions = (
            self.executor.recover_positions()
        )

        recovered: list[
            ManagedPosition
        ] = []

        broker_tickets: set[int] = set()

        for broker_position in broker_positions:

            ticket = int(
                broker_position.ticket
            )

            broker_tickets.add(
                ticket
            )

            managed = self.positions.get(
                ticket
            )

            if managed is None:

                managed = self.register_position(
                    broker_position
                )

            else:

                self._update_from_broker(
                    managed,
                    broker_position,
                )

            managed.metadata[
                "recovered"
            ] = True

            managed.metadata[
                "recovered_at"
            ] = time.time()

            managed.add_event(
                "RECOVERED",
                "Position recovered from MT5.",
            )

            recovered.append(
                managed
            )

            self.statistics.increment(
                "recovered"
            )

        #######################################################################
        # REMOVE STALE LOCAL POSITIONS
        #######################################################################

        if self.config.remove_missing_broker_positions:

            stale_tickets = [
                ticket
                for ticket in self.positions
                if ticket not in broker_tickets
            ]

            for ticket in stale_tickets:

                self.remove_position(
                    ticket,
                    ExitReason.BROKER_CLOSED,
                )

        self.last_sync = time.time()

        self.statistics.last_sync_time = (
            self.last_sync
        )

        return recovered

    ###########################################################################
    # REGISTER FROM EXECUTION RESULT
    ###########################################################################

    def register_execution_result(
        self,
        result,
    ) -> Optional[ManagedPosition]:
        """
        Resolve and register a newly executed trade.

        Some MT5 brokers return the order ticket rather than the final position
        ticket. A forced synchronization is therefore performed before lookup.
        """

        if result is None:
            return None

        if not bool(
            getattr(
                result,
                "success",
                False,
            )
        ):
            return None

        possible_ticket = (
            getattr(
                result,
                "position",
                None,
            )
            or getattr(
                result,
                "order",
                None,
            )
        )

        self.synchronize(
            force=True
        )

        #######################################################################
        # DIRECT TICKET MATCH
        #######################################################################

        if possible_ticket is not None:

            managed = self.positions.get(
                int(possible_ticket)
            )

            if managed is not None:

                managed.add_event(
                    "EXECUTION_REGISTERED",
                    "Position matched to execution result.",
                    execution_ticket=int(
                        possible_ticket
                    ),
                )

                return managed

        #######################################################################
        # FALLBACK MATCH USING EXECUTION DETAILS
        #######################################################################

        result_symbol = getattr(
            result,
            "symbol",
            None,
        )

        result_volume = getattr(
            result,
            "volume",
            None,
        )

        result_price = getattr(
            result,
            "price",
            None,
        )

        candidates = list(
            self.positions.values()
        )

        if result_symbol:

            candidates = [
                position
                for position in candidates
                if position.symbol == result_symbol
            ]

        if result_volume is not None:

            candidates = [
                position
                for position in candidates
                if math.isclose(
                    position.initial_volume,
                    float(result_volume),
                    rel_tol=1e-6,
                    abs_tol=1e-8,
                )
            ]

        if result_price is not None and candidates:

            matched = min(
                candidates,
                key=lambda position: abs(
                    position.entry_price
                    - float(result_price)
                ),
            )

        elif candidates:

            matched = max(
                candidates,
                key=lambda position: (
                    position.opened_at
                ),
            )

        else:

            return None

        matched.add_event(
            "EXECUTION_REGISTERED",
            "Position matched using execution details.",
            execution_ticket=possible_ticket,
        )

        return matched

    ###########################################################################
    # REFRESH ONE POSITION
    ###########################################################################

    def refresh_position(
        self,
        ticket: int,
    ) -> Optional[ManagedPosition]:
        """
        Refresh one position from the latest MT5 state.
        """

        ticket = int(
            ticket
        )

        broker_positions = (
            self.executor.positions(
                managed_only=True
            )
        )

        for broker_position in broker_positions:

            if (
                int(broker_position.ticket)
                != ticket
            ):
                continue

            managed = self.positions.get(
                ticket
            )

            if managed is None:

                managed = self.register_position(
                    broker_position
                )

            else:

                self._update_from_broker(
                    managed,
                    broker_position,
                )

            self.statistics.increment(
                "refreshed"
            )

            return managed

        #######################################################################
        # POSITION IS NO LONGER OPEN
        #######################################################################

        if (
            ticket in self.positions
            and self.config.remove_missing_broker_positions
        ):

            self.remove_position(
                ticket,
                ExitReason.BROKER_CLOSED,
            )

        return None

    ###########################################################################
    # UPDATE LOCAL POSITION FROM BROKER DATA
    ###########################################################################

    def _update_from_broker(
        self,
        managed: ManagedPosition,
        broker_position,
    ) -> ManagedPosition:
        """
        Update a managed position using current MT5 position information.
        """

        previous_volume = (
            managed.current_volume
        )

        previous_stop = (
            managed.current_stop_loss
        )

        previous_target = (
            managed.take_profit
        )

        current_volume = float(
            broker_position.volume
        )

        entry_price = float(
            broker_position.price_open
        )

        current_stop = float(
            getattr(
                broker_position,
                "sl",
                0.0,
            )
            or 0.0
        )

        current_target = float(
            getattr(
                broker_position,
                "tp",
                0.0,
            )
            or 0.0
        )

        current_price = float(
            getattr(
                broker_position,
                "price_current",
                entry_price,
            )
            or entry_price
        )

        floating_profit = float(
            getattr(
                broker_position,
                "profit",
                0.0,
            )
            or 0.0
        )

        managed.current_volume = (
            current_volume
        )

        managed.entry_price = (
            entry_price
        )

        managed.current_stop_loss = (
            current_stop
        )

        managed.take_profit = (
            current_target
        )

        managed.current_price = (
            current_price
        )

        managed.floating_profit = (
            floating_profit
        )

        managed.last_broker_sync = (
            time.time()
        )

        managed.update_price_extremes(
            current_price
        )

        #######################################################################
        # PRESERVE OR RECALCULATE ORIGINAL RISK
        #######################################################################

        if (
            not self.config.preserve_original_risk
            or not managed.has_valid_original_risk
        ):

            if current_stop > 0:

                managed.original_risk_per_unit = abs(
                    managed.entry_price
                    - current_stop
                )

                if managed.initial_stop_loss <= 0:

                    managed.initial_stop_loss = (
                        current_stop
                    )

        #######################################################################
        # DETECT VOLUME REDUCTION
        #######################################################################

        if (
            current_volume
            < previous_volume - EPSILON
        ):

            closed_volume = max(
                0.0,
                previous_volume
                - current_volume,
            )

            managed.add_event(
                "VOLUME_REDUCTION",
                "A position volume reduction was detected.",
                previous_volume=previous_volume,
                current_volume=current_volume,
                closed_volume=closed_volume,
            )

        #######################################################################
        # DETECT STOP-LOSS CHANGE
        #######################################################################

        if not math.isclose(
            current_stop,
            previous_stop,
            rel_tol=1e-9,
            abs_tol=EPSILON,
        ):

            managed.add_event(
                "STOP_UPDATED",
                "A stop-loss change was detected.",
                previous_stop=previous_stop,
                current_stop=current_stop,
            )

        #######################################################################
        # DETECT TAKE-PROFIT CHANGE
        #######################################################################

        if not math.isclose(
            current_target,
            previous_target,
            rel_tol=1e-9,
            abs_tol=EPSILON,
        ):

            managed.add_event(
                "TARGET_UPDATED",
                "A take-profit change was detected.",
                previous_target=previous_target,
                current_target=current_target,
            )

        #######################################################################
        # BROKER METADATA
        #######################################################################

        managed.metadata[
            "swap"
        ] = float(
            getattr(
                broker_position,
                "swap",
                0.0,
            )
            or 0.0
        )

        managed.metadata[
            "broker_comment"
        ] = str(
            getattr(
                broker_position,
                "comment",
                "",
            )
            or ""
        )

        managed.metadata[
            "broker_magic"
        ] = getattr(
            broker_position,
            "magic",
            None,
        )

        managed.metadata[
            "broker_reason"
        ] = getattr(
            broker_position,
            "reason",
            None,
        )

        return managed

    ###########################################################################
    # CONSISTENCY REPORT
    ###########################################################################

    def consistency_report(
        self,
    ) -> dict[str, Any]:
        """
        Compare the local position registry with current MT5 positions.
        """

        broker_positions = (
            self.executor.positions(
                managed_only=True
            )
        )

        broker_tickets = {
            int(position.ticket)
            for position in broker_positions
        }

        local_tickets = set(
            self.positions.keys()
        )

        missing_locally = sorted(
            broker_tickets
            - local_tickets
        )

        missing_at_broker = sorted(
            local_tickets
            - broker_tickets
        )

        matched = sorted(
            broker_tickets
            & local_tickets
        )

        return {
            "consistent": (
                not missing_locally
                and not missing_at_broker
            ),
            "broker_position_count": len(
                broker_tickets
            ),
            "local_position_count": len(
                local_tickets
            ),
            "matched": matched,
            "missing_locally": missing_locally,
            "missing_at_broker": missing_at_broker,
        }


    ###########################################################################
    # MANAGEMENT CYCLE
    ###########################################################################

    def manage_positions(
        self,
        atr_by_symbol: Optional[dict[str, float]] = None,
        *,
        force_sync: bool = False,
    ) -> dict[str, Any]:
        """Run one complete management cycle for all active positions.

        ``atr_by_symbol`` is optional. Break-even, R tracking, partial exits and
        time exits work without it. ATR is required only for ATR trailing.
        """

        started_at = time.time()
        synchronization = self.safe_synchronize(force=force_sync)
        atr_by_symbol = atr_by_symbol or {}

        reports: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for position in list(self.positions.values()):
            if position.state in {
                PositionState.CLOSED,
                PositionState.CLOSING,
                PositionState.ERROR,
            }:
                continue

            if (
                self.config.position_refresh_seconds > 0
                and started_at - position.last_management_time
                < self.config.position_refresh_seconds
            ):
                reports.append({
                    "ticket": position.ticket,
                    "managed": False,
                    "reason": "position_refresh_interval_not_reached",
                })
                continue

            try:
                reports.append(
                    self.evaluate_position(
                        position,
                        atr=atr_by_symbol.get(position.symbol),
                    )
                )
            except Exception as exc:
                self.statistics.increment("management_errors")
                position.add_event(
                    "MANAGEMENT_ERROR",
                    "Position management failed.",
                    error=str(exc),
                )
                errors.append({
                    "ticket": position.ticket,
                    "symbol": position.symbol,
                    "error": str(exc),
                })
                if self.config.raise_management_errors:
                    raise

        finished_at = time.time()
        self.last_management_cycle = finished_at
        self.statistics.last_management_time = finished_at

        return {
            "managed": True,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": round((finished_at - started_at) * 1000.0, 3),
            "synchronization": synchronization,
            "active_positions": self.active_count,
            "reports": reports,
            "errors": errors,
        }

    def evaluate_position(
        self,
        position: ManagedPosition | int,
        *,
        atr: Optional[float] = None,
    ) -> dict[str, Any]:
        """Evaluate and manage one position in a deterministic order."""

        managed = (
            self.get(position)
            if isinstance(position, int)
            else position
        )

        if managed is None:
            raise KeyError(f"Unknown managed position: {position}")

        if not managed.is_open:
            return {
                "ticket": managed.ticket,
                "managed": False,
                "reason": "position_not_open",
            }

        now = time.time()
        price = self._market_exit_price(managed)
        self._update_position_metrics(managed, price)

        actions: list[dict[str, Any]] = []

        # Time protection takes precedence over profit-management actions.
        time_action = self._try_time_exit(managed)
        if time_action is not None:
            actions.append(time_action)
            managed.last_management_time = now
            return self._evaluation_report(managed, actions)

        # Lock risk first, then scale out, then trail the remaining position.
        break_even_action = self._try_break_even(managed)
        if break_even_action is not None:
            actions.append(break_even_action)

        tp1_action = self._try_tp1(managed)
        if tp1_action is not None:
            actions.append(tp1_action)

        # Refresh after a possible TP1 volume change before calculating TP2.
        if tp1_action and tp1_action.get("success"):
            refreshed = self.refresh_position(managed.ticket)
            if refreshed is None:
                managed.last_management_time = now
                return self._evaluation_report(managed, actions)
            managed = refreshed

        tp2_action = self._try_tp2(managed)
        if tp2_action is not None:
            actions.append(tp2_action)

        if tp2_action and tp2_action.get("success"):
            refreshed = self.refresh_position(managed.ticket)
            if refreshed is None:
                managed.last_management_time = now
                return self._evaluation_report(managed, actions)
            managed = refreshed

        trailing_action = self._try_trailing_stop(managed, atr=atr)
        if trailing_action is not None:
            actions.append(trailing_action)

        managed.last_management_time = now
        return self._evaluation_report(managed, actions)

    ###########################################################################
    # POSITION METRICS
    ###########################################################################

    def calculate_rr(
        self,
        position: ManagedPosition,
        price: Optional[float] = None,
    ) -> float:
        """Return signed unrealized R using the preserved initial risk."""

        if not position.has_valid_original_risk:
            return 0.0

        resolved_price = (
            position.current_price
            if price is None
            else float(price)
        )

        if resolved_price is None or not math.isfinite(resolved_price):
            return 0.0

        movement = (
            resolved_price - position.entry_price
            if position.is_buy
            else position.entry_price - resolved_price
        )

        return movement / position.original_risk_per_unit

    def _update_position_metrics(
        self,
        position: ManagedPosition,
        price: float,
    ) -> None:
        position.update_price_extremes(price)
        position.current_rr = self.calculate_rr(position, price)
        position.maximum_favorable_rr = max(
            position.maximum_favorable_rr,
            position.current_rr,
        )
        position.maximum_adverse_rr = min(
            position.maximum_adverse_rr,
            position.current_rr,
        )
        position.metadata["last_metric_update"] = time.time()

    def _market_exit_price(self, position: ManagedPosition) -> float:
        """Use the executable side of the current quote."""

        tick = self.executor.symbol_tick(position.symbol)
        price = tick.bid if position.is_buy else tick.ask
        price = float(price)

        if not math.isfinite(price) or price <= 0:
            raise ValueError(
                f"Invalid market price for {position.symbol}: {price}"
            )

        return price

    ###########################################################################
    # BREAK EVEN
    ###########################################################################

    def _try_break_even(
        self,
        position: ManagedPosition,
    ) -> Optional[dict[str, Any]]:
        if not self.config.enable_break_even:
            return None
        if position.break_even_done:
            return None
        if not position.has_valid_original_risk:
            return None
        if position.current_rr + EPSILON < self.config.break_even_trigger_rr:
            return None

        target_stop = self._break_even_stop(position)

        # Never loosen an existing stop.
        if position.is_buy and position.current_stop_loss >= target_stop - EPSILON:
            position.break_even_done = True
            position.state = PositionState.BREAK_EVEN
            return {
                "action": "BREAK_EVEN",
                "success": True,
                "skipped_execution": True,
                "reason": "stop_already_at_or_above_break_even",
                "stop_loss": position.current_stop_loss,
            }

        if (
            position.is_sell
            and position.current_stop_loss > 0
            and position.current_stop_loss <= target_stop + EPSILON
        ):
            position.break_even_done = True
            position.state = PositionState.BREAK_EVEN
            return {
                "action": "BREAK_EVEN",
                "success": True,
                "skipped_execution": True,
                "reason": "stop_already_at_or_below_break_even",
                "stop_loss": position.current_stop_loss,
            }

        try:
            if abs(target_stop - position.entry_price) <= EPSILON:
                result = self.executor.move_to_break_even(position.ticket)
            else:
                result = self.executor.modify_protection(
                    position.ticket,
                    target_stop,
                    position.take_profit,
                )
        except Exception as exc:
            self.statistics.increment("execution_errors")
            position.add_event(
                "BREAK_EVEN_FAILED",
                "Break-even update failed.",
                error=str(exc),
                target_stop=target_stop,
            )
            return {
                "action": "BREAK_EVEN",
                "success": False,
                "error": str(exc),
                "target_stop": target_stop,
            }

        success = bool(getattr(result, "success", False))
        if success:
            position.break_even_done = True
            position.state = PositionState.BREAK_EVEN
            position.current_stop_loss = target_stop
            self.statistics.increment("break_even_updates")
            position.add_event(
                "BREAK_EVEN",
                "Stop moved to break-even.",
                stop_loss=target_stop,
                rr=position.current_rr,
            )

        return {
            "action": "BREAK_EVEN",
            "success": success,
            "target_stop": target_stop,
            "result": self._result_payload(result),
        }

    def _break_even_stop(self, position: ManagedPosition) -> float:
        info = self.executor.symbol_info(position.symbol)
        offset = (
            self.config.break_even_offset_points
            * float(info.point)
        )
        raw = (
            position.entry_price + offset
            if position.is_buy
            else position.entry_price - offset
        )
        return round(raw, int(info.digits))

    ###########################################################################
    # PARTIAL PROFIT MANAGEMENT
    ###########################################################################

    def _try_tp1(
        self,
        position: ManagedPosition,
    ) -> Optional[dict[str, Any]]:
        if not self.config.enable_tp1 or position.tp1_done:
            return None
        if position.current_rr + EPSILON < self.config.tp1_trigger_rr:
            return None

        return self._execute_partial_stage(
            position,
            stage="TP1",
            requested_volume=(
                position.initial_volume
                * self.config.tp1_close_ratio
            ),
        )

    def _try_tp2(
        self,
        position: ManagedPosition,
    ) -> Optional[dict[str, Any]]:
        if not self.config.enable_tp2 or position.tp2_done:
            return None
        if position.current_rr + EPSILON < self.config.tp2_trigger_rr:
            return None

        return self._execute_partial_stage(
            position,
            stage="TP2",
            requested_volume=(
                position.initial_volume
                * self.config.tp2_close_ratio
            ),
        )

    def _execute_partial_stage(
        self,
        position: ManagedPosition,
        *,
        stage: str,
        requested_volume: float,
    ) -> dict[str, Any]:
        volume = self._safe_partial_volume(
            position,
            requested_volume,
        )

        if volume <= EPSILON:
            # Small positions may be unable to support a legal partial close.
            position.add_event(
                f"{stage}_SKIPPED",
                "Partial close skipped because broker volume rules leave no valid size.",
                requested_volume=requested_volume,
                current_volume=position.current_volume,
            )
            return {
                "action": stage,
                "success": False,
                "reason": "no_valid_partial_volume",
                "requested_volume": requested_volume,
            }

        try:
            result = self.executor.partial_close(
                position.ticket,
                volume,
                comment=f"AAQTS {stage}",
            )
        except Exception as exc:
            self.statistics.increment("execution_errors")
            position.add_event(
                f"{stage}_FAILED",
                f"{stage} partial close failed.",
                error=str(exc),
                volume=volume,
            )
            return {
                "action": stage,
                "success": False,
                "error": str(exc),
                "volume": volume,
            }

        success = bool(getattr(result, "success", False))
        if success:
            position.current_volume = max(
                0.0,
                position.current_volume - volume,
            )
            self.statistics.increment("partial_closes")

            if stage == "TP1":
                position.tp1_done = True
                position.state = PositionState.TP1
                self.statistics.increment("tp1_executions")
            else:
                position.tp2_done = True
                position.state = PositionState.TP2
                self.statistics.increment("tp2_executions")

                if self.config.enable_runner and self.config.runner_after_tp2:
                    position.state = PositionState.RUNNER
                    self.statistics.increment("runner_positions")
                    position.add_event(
                        "RUNNER",
                        "Remaining position promoted to runner.",
                        remaining_volume=position.current_volume,
                    )

            position.add_event(
                stage,
                f"{stage} partial close executed.",
                volume=volume,
                rr=position.current_rr,
            )

        return {
            "action": stage,
            "success": success,
            "volume": volume,
            "result": self._result_payload(result),
        }

    def _safe_partial_volume(
        self,
        position: ManagedPosition,
        requested_volume: float,
    ) -> float:
        """Return a legal partial volume while preserving broker minimum size."""

        info = self.executor.symbol_info(position.symbol)
        minimum = float(info.volume_min)
        step = float(info.volume_step)
        current = float(position.current_volume)

        if current <= minimum + EPSILON:
            return 0.0

        requested = min(float(requested_volume), current - minimum)
        if requested < minimum - EPSILON:
            return 0.0

        steps = math.floor((requested + EPSILON) / step)
        normalized = steps * step
        precision = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]))
        normalized = round(normalized, precision)

        remaining = current - normalized
        if normalized < minimum - EPSILON:
            return 0.0
        if remaining < minimum - EPSILON:
            normalized = current - minimum
            steps = math.floor((normalized + EPSILON) / step)
            normalized = round(steps * step, precision)

        if normalized <= EPSILON or normalized >= current - EPSILON:
            return 0.0

        return normalized

    ###########################################################################
    # ATR TRAILING STOP
    ###########################################################################

    def _try_trailing_stop(
        self,
        position: ManagedPosition,
        *,
        atr: Optional[float],
    ) -> Optional[dict[str, Any]]:
        if not self.config.enable_trailing_stop:
            return None
        if position.current_rr + EPSILON < self.config.trailing_start_rr:
            return None
        if atr is None:
            return None

        atr = float(atr)
        if not math.isfinite(atr) or atr <= 0:
            return None

        candidate = self._trailing_stop_candidate(position, atr)
        if candidate is None:
            return None

        try:
            result = self.executor.update_trailing_stop(
                position.ticket,
                candidate,
            )
        except Exception as exc:
            self.statistics.increment("execution_errors")
            position.add_event(
                "TRAILING_FAILED",
                "Trailing-stop update failed.",
                error=str(exc),
                target_stop=candidate,
                atr=atr,
            )
            return {
                "action": "TRAILING_STOP",
                "success": False,
                "error": str(exc),
                "target_stop": candidate,
            }

        success = bool(getattr(result, "success", False))
        if success:
            position.trailing_active = True
            position.current_stop_loss = candidate
            self.statistics.increment("trailing_updates")
            position.add_event(
                "TRAILING_STOP",
                "Trailing stop advanced.",
                stop_loss=candidate,
                atr=atr,
                rr=position.current_rr,
            )

        return {
            "action": "TRAILING_STOP",
            "success": success,
            "target_stop": candidate,
            "result": self._result_payload(result),
        }

    def _trailing_stop_candidate(
        self,
        position: ManagedPosition,
        atr: float,
    ) -> Optional[float]:
        info = self.executor.symbol_info(position.symbol)
        point = float(info.point)
        digits = int(info.digits)
        distance = max(
            atr * self.config.trailing_atr_multiplier,
            self.config.minimum_trailing_distance_points * point,
        )

        if position.is_buy:
            anchor = float(position.highest_price or position.current_price)
            candidate = anchor - distance
            # A trailing update must not weaken current protection.
            if candidate <= position.current_stop_loss + point * 0.5:
                return None
            # Once break-even is active, do not trail below its protected level.
            if position.break_even_done:
                candidate = max(candidate, self._break_even_stop(position))
        else:
            anchor = float(position.lowest_price or position.current_price)
            candidate = anchor + distance
            if (
                position.current_stop_loss > 0
                and candidate >= position.current_stop_loss - point * 0.5
            ):
                return None
            if position.break_even_done:
                candidate = min(candidate, self._break_even_stop(position))

        candidate = round(candidate, digits)
        if candidate <= 0:
            return None

        return candidate

    ###########################################################################
    # TIME, SESSION AND EMERGENCY EXITS
    ###########################################################################

    def _try_time_exit(
        self,
        position: ManagedPosition,
    ) -> Optional[dict[str, Any]]:
        if not self.config.enable_time_exit:
            return None
        if position.age_minutes + EPSILON < self.config.maximum_trade_minutes:
            return None

        result = self.close_managed_position(
            position.ticket,
            reason=ExitReason.TIME_EXIT,
            comment="AAQTS Time Exit",
        )
        if result.get("success"):
            self.statistics.increment("time_exits")
        return result

    def close_managed_position(
        self,
        ticket: int,
        *,
        reason: ExitReason = ExitReason.MANUAL,
        comment: str = "AAQTS Close",
    ) -> dict[str, Any]:
        """Close one position and archive it after broker confirmation."""

        position = self.get(ticket)
        if position is None:
            return {
                "action": "CLOSE",
                "success": False,
                "ticket": int(ticket),
                "reason": "position_not_registered",
            }

        previous_state = position.state
        position.state = PositionState.CLOSING

        try:
            result = self.executor.close_position(
                position.ticket,
                comment=comment,
            )
        except Exception as exc:
            position.state = previous_state
            self.statistics.increment("execution_errors")
            position.add_event(
                "CLOSE_FAILED",
                "Position close failed.",
                error=str(exc),
                reason=reason.value,
            )
            if self.config.raise_management_errors:
                raise
            return {
                "action": "CLOSE",
                "success": False,
                "ticket": position.ticket,
                "reason": reason.value,
                "error": str(exc),
            }

        success = bool(getattr(result, "success", False))
        if success:
            self.remove_position(position.ticket, reason)
        else:
            position.state = previous_state

        return {
            "action": "CLOSE",
            "success": success,
            "ticket": position.ticket,
            "reason": reason.value,
            "result": self._result_payload(result),
        }

    def session_exit_all(
        self,
        *,
        comment: str = "AAQTS Session Exit",
    ) -> list[dict[str, Any]]:
        """Close all managed positions for an explicit session boundary."""

        reports: list[dict[str, Any]] = []
        for ticket in list(self.positions):
            report = self.close_managed_position(
                ticket,
                reason=ExitReason.SESSION_CLOSE,
                comment=comment,
            )
            reports.append(report)
            if report.get("success"):
                self.statistics.increment("session_exits")
        return reports

    def emergency_exit_all(self) -> list[dict[str, Any]]:
        """Pause new entries and close every registered position."""

        self.executor.pause()
        reports: list[dict[str, Any]] = []
        for ticket in list(self.positions):
            report = self.close_managed_position(
                ticket,
                reason=ExitReason.EMERGENCY,
                comment="AAQTS Emergency Close",
            )
            reports.append(report)
            if report.get("success"):
                self.statistics.increment("emergency_exits")
        return reports

    ###########################################################################
    # REPORTING AND ANALYTICS
    ###########################################################################

    def position_report(
        self,
        ticket: int,
        *,
        include_events: bool = True,
    ) -> Optional[dict[str, Any]]:
        position = self.get(ticket)
        if position is None:
            position = next(
                (
                    item
                    for item in reversed(self.closed_positions)
                    if item.ticket == int(ticket)
                ),
                None,
            )
        return (
            position.to_dict(include_events=include_events)
            if position is not None
            else None
        )

    def portfolio_report(self) -> dict[str, Any]:
        active = list(self.positions.values())
        buy_count = sum(1 for item in active if item.is_buy)
        sell_count = len(active) - buy_count
        total_initial_volume = sum(item.initial_volume for item in active)
        total_current_volume = sum(item.current_volume for item in active)
        floating_profit = sum(item.floating_profit for item in active)
        rr_values = [item.current_rr for item in active]

        return {
            "version": POSITION_MANAGER_VERSION,
            "generated_at": time.time(),
            "active_count": len(active),
            "closed_history_count": len(self.closed_positions),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "total_initial_volume": total_initial_volume,
            "total_current_volume": total_current_volume,
            "floating_profit": floating_profit,
            "average_current_rr": (
                sum(rr_values) / len(rr_values)
                if rr_values
                else 0.0
            ),
            "maximum_current_rr": max(rr_values) if rr_values else 0.0,
            "minimum_current_rr": min(rr_values) if rr_values else 0.0,
            "break_even_count": sum(
                1 for item in active if item.break_even_done
            ),
            "trailing_count": sum(
                1 for item in active if item.trailing_active
            ),
            "runner_count": sum(
                1 for item in active if item.state == PositionState.RUNNER
            ),
            "statistics": self.statistics.to_dict(),
            "positions": [
                item.to_dict(include_events=False)
                for item in active
            ],
        }

    def closed_history(
        self,
        *,
        limit: Optional[int] = None,
        include_events: bool = False,
    ) -> list[dict[str, Any]]:
        history = self.closed_positions
        if limit is not None:
            history = history[-max(0, int(limit)):]
        return [
            item.to_dict(include_events=include_events)
            for item in history
        ]

    def health_report(self) -> dict[str, Any]:
        consistency: dict[str, Any]
        try:
            consistency = self.consistency_report()
        except Exception as exc:
            consistency = {
                "consistent": False,
                "error": str(exc),
            }

        invalid_positions = []
        for position in self.positions.values():
            issues = []
            if not position.has_valid_original_risk:
                issues.append("missing_original_risk")
            if position.current_volume <= 0:
                issues.append("invalid_current_volume")
            if position.current_price is None or position.current_price <= 0:
                issues.append("invalid_current_price")
            if issues:
                invalid_positions.append({
                    "ticket": position.ticket,
                    "issues": issues,
                })

        return {
            "healthy": (
                consistency.get("consistent", False)
                and not invalid_positions
            ),
            "version": POSITION_MANAGER_VERSION,
            "active_count": self.active_count,
            "consistency": consistency,
            "invalid_positions": invalid_positions,
            "statistics": self.statistics.to_dict(),
        }

    ###########################################################################
    # INTERNAL SERIALIZATION HELPERS
    ###########################################################################

    @staticmethod
    def _result_payload(result: Any) -> Optional[dict[str, Any]]:
        if result is None:
            return None
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return dict(result)
        return {
            "success": bool(getattr(result, "success", False)),
            "retcode": getattr(result, "retcode", None),
            "comment": str(getattr(result, "comment", "")),
            "order": getattr(result, "order", None),
            "deal": getattr(result, "deal", None),
            "position": getattr(result, "position", None),
        }

    @staticmethod
    def _evaluation_report(
        position: ManagedPosition,
        actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "ticket": position.ticket,
            "symbol": position.symbol,
            "side": position.side,
            "managed": True,
            "state": position.state.value,
            "current_price": position.current_price,
            "current_rr": position.current_rr,
            "maximum_favorable_rr": position.maximum_favorable_rr,
            "maximum_adverse_rr": position.maximum_adverse_rr,
            "current_volume": position.current_volume,
            "break_even_done": position.break_even_done,
            "tp1_done": position.tp1_done,
            "tp2_done": position.tp2_done,
            "trailing_active": position.trailing_active,
            "actions": actions,
        }