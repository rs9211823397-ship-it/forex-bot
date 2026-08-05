"""Production adapter for the immutable Phase 6 contextual engine."""

from dataclasses import dataclass

import pandas as pd

from data.timeframes import (
    TimeframeError,
    candle_close_times,
    normalize_timestamp,
)
from price_action.context import (
    ContextEngine,
    ProtectedSwing,
    RegimeState,
    StructureState
)
from price_action.contextual_trigger import (
    ContextualTriggerEngine,
    SetupContext,
    TriggerOutput
)


@dataclass(frozen=True)
class CausalMarketData:
    enabled: bool
    lower: object
    higher: object | None
    decision_time: pd.Timestamp | None
    bar_duration: pd.Timedelta | None
    htf_confirmed_at: pd.Timestamp | None


@dataclass(frozen=True)
class ContextualGateResult:
    enabled: bool
    approved: bool
    direction: str | None
    trigger: str
    reasons: tuple[str, ...]
    output: TriggerOutput | None = None

    @classmethod
    def bypassed(cls):
        return cls(
            enabled=False,
            approved=True,
            direction=None,
            trigger="BYPASSED",
            reasons=()
        )

    @classmethod
    def rejected(cls, reason):
        return cls(
            enabled=True,
            approved=False,
            direction=None,
            trigger="NONE",
            reasons=(
                "Contextual Trigger: NONE",
                f"Contextual {reason}"
            )
        )


def _attach_close_time(data):
    frame = data.copy()
    close_time_column = next(
        (
            column for column in frame.columns
            if str(column).lower() == "close_time"
        ),
        None
    )

    if close_time_column is not None:
        if close_time_column != "close_time":
            frame.rename(
                columns={close_time_column: "close_time"},
                inplace=True
            )
    elif not isinstance(frame.index, pd.DatetimeIndex):
        return None

    try:
        frame["close_time"] = candle_close_times(
            frame,
            frame.attrs.get("timeframe"),
        )
    except TimeframeError as exc:
        raise ValueError(str(exc)) from exc
    return frame


def _closed_frame(frame, decision_time):
    result = frame.copy()
    result["close_time"] = pd.to_datetime(
        result["close_time"],
        utc=True,
        errors="raise"
    )
    result = result.loc[
        result["close_time"] <= decision_time
    ].copy()

    if result.empty:
        raise ValueError(
            "No closed candles are available at decision_time"
        )

    return result


def _infer_bar_duration(frame):
    close_times = frame["close_time"].drop_duplicates()

    if len(close_times) < 2:
        return pd.Timedelta(0)

    duration = (
        close_times.iloc[-1]
        - close_times.iloc[-2]
    )

    if duration <= pd.Timedelta(0):
        return pd.Timedelta(0)

    return duration


def prepare_causal_market_data(data, higher_tf=None):
    lower = _attach_close_time(data)

    if lower is None:
        return CausalMarketData(
            enabled=False,
            lower=data,
            higher=higher_tf,
            decision_time=None,
            bar_duration=None,
            htf_confirmed_at=None
        )

    requested_decision_time = data.attrs.get(
        "decision_time"
    )
    decision_time = normalize_timestamp(
        requested_decision_time
        if requested_decision_time is not None
        else lower["close_time"].iloc[-1]
    )
    lower = _closed_frame(
        lower,
        decision_time
    )
    bar_duration = _infer_bar_duration(lower)

    prepared_higher = None
    htf_confirmed_at = None

    if higher_tf is not None:
        annotated_higher = _attach_close_time(higher_tf)

        if annotated_higher is not None:
            try:
                prepared_higher = _closed_frame(
                    annotated_higher,
                    decision_time
                )
            except ValueError:
                prepared_higher = None
            else:
                htf_confirmed_at = normalize_timestamp(
                    prepared_higher["close_time"].iloc[-1]
                )

    return CausalMarketData(
        enabled=True,
        lower=lower,
        higher=prepared_higher,
        decision_time=decision_time,
        bar_duration=bar_duration,
        htf_confirmed_at=htf_confirmed_at
    )


class ContextualProductionAdapter:

    def __init__(
        self,
        context_engine=None,
        trigger_engine=None
    ):
        self.context_engine = (
            context_engine or ContextEngine()
        )
        self.trigger_engine = (
            trigger_engine or ContextualTriggerEngine()
        )

    def _protected_swing(
        self,
        events,
        kind,
        normalized_data,
        lookback,
        decision_time
    ):
        if not events:
            return None

        event = events[-1]
        formed_position = int(event["index"])
        confirmed_position = formed_position + lookback

        if (
            formed_position < 0
            or confirmed_position >= len(normalized_data)
        ):
            return None

        formed_at = normalize_timestamp(
            normalized_data.iloc[
                formed_position
            ]["close_time"]
        )
        confirmed_at = normalize_timestamp(
            normalized_data.iloc[
                confirmed_position
            ]["close_time"]
        )

        if confirmed_at > decision_time:
            return None

        return ProtectedSwing(
            kind=kind,
            price=float(event["price"]),
            formed_at=formed_at,
            confirmed_at=confirmed_at
        )

    def confirmed_swings(
        self,
        data,
        market_structure,
        decision_time
    ):
        normalized = data.copy()
        normalized.columns = [
            str(column).lower()
            for column in normalized.columns
        ]
        normalized = normalized.tail(300)
        state_method = getattr(
            market_structure,
            "state",
            None,
        )
        if callable(state_method):
            state = state_method(
                data,
                decision_time=decision_time,
            )

            def convert(event, kind):
                if event is None:
                    return None
                return ProtectedSwing(
                    kind=kind,
                    price=float(event.price),
                    formed_at=normalize_timestamp(
                        event.formed_at
                    ),
                    confirmed_at=normalize_timestamp(
                        event.confirmed_at
                    ),
                )

            return (
                convert(state.protected_high, "HIGH"),
                convert(state.protected_low, "LOW"),
            )

        highs, lows = market_structure.find_swings(data)
        lookback = int(market_structure.lookback)

        return (
            self._protected_swing(
                highs,
                "HIGH",
                normalized,
                lookback,
                decision_time
            ),
            self._protected_swing(
                lows,
                "LOW",
                normalized,
                lookback,
                decision_time
            )
        )

    def build_context(
        self,
        data,
        decision_time,
        regime,
        structure,
        market_structure
    ):
        if regime.confirmed_at is None:
            return None

        protected_high, protected_low = (
            self.confirmed_swings(
                data=data,
                market_structure=market_structure,
                decision_time=decision_time
            )
        )

        return self.context_engine.build(
            data=data,
            decision_time=decision_time,
            htf_regime=RegimeState(
                regime=regime.regime,
                confirmed_at=regime.confirmed_at
            ),
            structure=StructureState(
                trend=structure.trend,
                confirmed_at=structure.confirmed_at
            ),
            protected_swing_high=protected_high,
            protected_swing_low=protected_low
        )

    def evaluate_trigger(
        self,
        context,
        setup: SetupContext | None
    ):
        if context is None:
            return ContextualGateResult.rejected(
                "HTF_STATE_UNAVAILABLE"
            )

        output = self.trigger_engine.evaluate(
            context,
            setup
        )
        approved = (
            setup is not None
            and output.trigger != "NONE"
            and output.direction == setup.direction
        )
        reasons = (
            f"Contextual Trigger: {output.trigger}",
            f"Contextual Location: {output.location}",
            f"Contextual Liquidity: {output.liquidity_event}",
            f"Contextual Candle Quality: {output.candle_quality}",
        ) + tuple(
            f"Contextual {code}"
            for code in output.reason_codes
        )

        return ContextualGateResult(
            enabled=True,
            approved=approved,
            direction=(
                setup.direction
                if setup is not None
                else None
            ),
            trigger=output.trigger,
            reasons=reasons,
            output=output
        )
