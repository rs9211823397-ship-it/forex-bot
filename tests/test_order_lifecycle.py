from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from execution.models import OrderRequest, OrderSide, OrderState
from execution.order_manager import OrderLifecycleError, OrderManager
from execution.simulation import BrokerSimulationConfig, BrokerSimulator
from execution.trade_manager import TradeManager
from risk.instrument import InstrumentSpec


NOW = datetime(2025, 1, 1, tzinfo=timezone.utc)


def instrument(**overrides):
    values = {
        "symbol": "TEST",
        "tick_size": 0.01,
        "contract_multiplier": 1.0,
        "quantity_step": 0.1,
        "minimum_quantity": 0.1,
        "maximum_quantity": 100.0,
        "spread": 0.2,
        "slippage": 0.1,
        "commission_per_quantity": 0.5,
    }
    values.update(overrides)
    return InstrumentSpec(**values)


def request(
    client_order_id="client-1",
    side="BUY",
    quantity=10.0,
    **overrides,
):
    values = {
        "client_order_id": client_order_id,
        "symbol": "TEST",
        "side": side,
        "quantity": quantity,
        "created_time": NOW,
    }
    values.update(overrides)
    return OrderRequest(**values)


def test_buy_and_sell_fills_include_adverse_costs():
    buy_simulator = BrokerSimulator(instrument())
    sell_simulator = BrokerSimulator(instrument())
    buy = buy_simulator.submit(request(side="BUY"))
    sell = sell_simulator.submit(
        request(client_order_id="sell-1", side="SELL")
    )

    buy_update = buy_simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=1),
    )[0]
    sell_update = sell_simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=1),
    )[0]

    assert buy.state is OrderState.ACKNOWLEDGED
    assert sell.state is OrderState.ACKNOWLEDGED
    assert buy_update.state is OrderState.FILLED
    assert sell_update.state is OrderState.FILLED
    assert buy_update.average_fill_price == pytest.approx(100.2)
    assert sell_update.average_fill_price == pytest.approx(99.8)
    assert buy_update.commission == pytest.approx(5.0)
    assert sell_update.commission == pytest.approx(5.0)


def test_config_can_override_spread_slippage_and_commission():
    simulator = BrokerSimulator(
        instrument(spread=9.0, slippage=9.0),
        BrokerSimulationConfig(
            spread=0.4,
            slippage=0.2,
            commission_per_quantity=1.25,
        ),
    )
    simulator.submit(request(quantity=2.0))
    result = simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=1),
    )[0]

    assert result.average_fill_price == pytest.approx(100.4)
    assert result.commission == pytest.approx(2.5)


@pytest.mark.parametrize(
    "side, limit_price, first_price, second_price, expected_fill",
    [
        ("BUY", 99.95, 100.0, 99.7, 99.9),
        ("SELL", 100.05, 100.0, 100.3, 100.1),
    ],
)
def test_limit_order_waits_for_price_and_never_fills_worse_than_limit(
    side,
    limit_price,
    first_price,
    second_price,
    expected_fill,
):
    simulator = BrokerSimulator(instrument())
    simulator.submit(
        request(
            side=side,
            order_type="LIMIT",
            limit_price=limit_price,
        )
    )

    assert simulator.process_bar(
        first_price,
        NOW + timedelta(minutes=1),
    ) == ()
    filled = simulator.process_bar(
        second_price,
        NOW + timedelta(minutes=2),
    )[0]

    assert filled.state is OrderState.FILLED
    assert filled.average_fill_price == pytest.approx(expected_fill)


def test_simulated_rejection_is_terminal():
    simulator = BrokerSimulator(
        instrument(),
        BrokerSimulationConfig(rejection_probability=1.0),
    )

    result = simulator.submit(request())

    assert result.state is OrderState.REJECTED
    assert result.reason == "SIMULATED_BROKER_REJECTION"
    assert simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=1),
    ) == ()


def test_partial_fill_then_final_fill():
    simulator = BrokerSimulator(
        instrument(),
        BrokerSimulationConfig(
            partial_fill_probability=1.0,
            partial_fill_ratio=0.4,
        ),
    )
    submitted = simulator.submit(request(quantity=10.0))

    first = simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=1),
    )[0]
    second = simulator.process_bar(
        101.0,
        NOW + timedelta(minutes=2),
    )[0]

    assert submitted.state is OrderState.ACKNOWLEDGED
    assert first.state is OrderState.PARTIALLY_FILLED
    assert first.filled_quantity == 4.0
    assert second.state is OrderState.FILLED
    assert second.filled_quantity == 10.0
    assert second.average_fill_price == pytest.approx(100.8)
    assert len(simulator.order_manager.fills) == 2


def test_latency_delays_fill_by_configured_bars():
    simulator = BrokerSimulator(
        instrument(),
        BrokerSimulationConfig(latency_bars=2),
    )
    simulator.submit(request())

    assert simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=1),
    ) == ()
    assert simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=2),
    ) == ()
    result = simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=3),
    )[0]

    assert result.state is OrderState.FILLED


def test_timeout_expires_order_before_delayed_fill():
    simulator = BrokerSimulator(
        instrument(),
        BrokerSimulationConfig(
            latency_bars=3,
            timeout_bars=2,
        ),
    )
    simulator.submit(request())

    assert simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=1),
    ) == ()
    result = simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=2),
    )[0]

    assert result.state is OrderState.EXPIRED
    assert result.reason == "EXECUTION_TIMEOUT"


def test_duplicate_client_order_id_is_idempotent():
    simulator = BrokerSimulator(instrument())
    first = simulator.submit(request())
    second = simulator.submit(request())

    assert first.order_id == second.order_id
    assert len(simulator.order_manager.events) == 3
    assert simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=1),
    )[0].state is OrderState.FILLED

    final = simulator.submit(request())
    assert final.state is OrderState.FILLED
    assert len(simulator.order_manager.fills) == 1


def test_normalized_duplicate_client_order_id_is_idempotent():
    simulator = BrokerSimulator(instrument())

    first = simulator.submit(request(quantity=1.29))
    second = simulator.submit(request(quantity=1.29))

    assert first.order_id == second.order_id
    assert second.request.quantity == pytest.approx(1.2)
    assert len(simulator.order_manager.events) == 3


def test_client_order_id_cannot_describe_a_different_order():
    simulator = BrokerSimulator(instrument())
    simulator.submit(request())

    with pytest.raises(
        OrderLifecycleError,
        match="different request",
    ):
        simulator.submit(request(side="SELL"))


def test_invalid_lifecycle_transition_is_rejected():
    manager = OrderManager()
    created = manager.create(request())

    with pytest.raises(
        OrderLifecycleError,
        match="CREATED -> FILLED",
    ):
        manager.record_fill(
            created.order_id,
            quantity=10.0,
            reference_price=100.0,
            price=100.0,
            commission=0.0,
            fill_time=NOW,
        )


def test_seed_makes_random_execution_reproducible():
    config = BrokerSimulationConfig(
        random_slippage=0.4,
        partial_fill_probability=0.5,
        seed=73,
    )

    def simulate():
        simulator = BrokerSimulator(instrument(), config)
        simulator.submit(request())
        first = simulator.process_bar(
            100.0,
            NOW + timedelta(minutes=1),
        )
        second = simulator.process_bar(
            101.0,
            NOW + timedelta(minutes=2),
        )
        return [
            (
                event.state,
                event.fill.quantity if event.fill else None,
                event.fill.price if event.fill else None,
            )
            for event in simulator.order_manager.events
        ], first, second

    first_events, first_update, first_final = simulate()
    second_events, second_update, second_final = simulate()

    assert first_events == second_events
    assert first_update == second_update
    assert first_final == second_final


def test_quantity_is_tick_normalized_and_invalid_minimum_rejected():
    normalized_simulator = BrokerSimulator(instrument())
    normalized = normalized_simulator.submit(request(quantity=1.29))

    rejected_simulator = BrokerSimulator(instrument())
    rejected = rejected_simulator.submit(
        request(client_order_id="small", quantity=0.05)
    )

    assert normalized.request.quantity == pytest.approx(1.2)
    assert rejected.state is OrderState.REJECTED
    assert rejected.reason == "INVALID_NORMALIZED_QUANTITY"


def test_event_history_is_ordered_and_reconciliation_friendly():
    simulator = BrokerSimulator(instrument())
    submitted = simulator.submit(request())
    simulator.process_bar(
        100.0,
        NOW + timedelta(minutes=1),
    )

    history = simulator.order_manager.history(submitted.order_id)

    assert [event.sequence for event in history] == [1, 2, 3, 4]
    assert [event.state for event in history] == [
        OrderState.CREATED,
        OrderState.SUBMITTED,
        OrderState.ACKNOWLEDGED,
        OrderState.FILLED,
    ]
    assert history[-1].fill is not None


def test_execution_contract_rejects_ambiguous_or_non_utc_timestamps():
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        request(created_time=datetime(2025, 1, 1))

    with pytest.raises(ValueError, match="must use UTC"):
        request(
            created_time=datetime(
                2025,
                1,
                1,
                tzinfo=timezone(timedelta(hours=5, minutes=30)),
            )
        )


def test_trade_manager_legacy_calculate_trade_api_is_unchanged():
    data = pd.DataFrame(
        {
            "close": [101.5],
            "ATR": [1.25],
        }
    )

    result = TradeManager().calculate_trade(data, {"signal": "BUY"})

    assert result == {
        "current_price": 101.5,
        "atr": 1.25,
    }
