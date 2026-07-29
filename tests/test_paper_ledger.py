from datetime import datetime, timezone

from broker.contracts import BrokerFillSnapshot
from execution.models import OrderSide
from paper.ledger import PaperLedger


def fill(
    *,
    fill_id: str,
    side: OrderSide,
    quantity: float,
    price: float,
    commission: float = 0.0,
) -> BrokerFillSnapshot:
    return BrokerFillSnapshot(
        fill_id=fill_id,
        order_id="order-1",
        account_id="paper",
        symbol="EURUSD",
        side=side,
        quantity=quantity,
        price=price,
        commission=commission,
        fill_time=datetime.now(timezone.utc),
    )


def test_open_long_position():
    ledger = PaperLedger("paper")

    ledger.apply_fill(
        fill(
            fill_id="1",
            side=OrderSide.BUY,
            quantity=1,
            price=100,
        )
    )

    position = ledger.positions()[0]

    assert position.quantity == 1
    assert position.average_price == 100
    assert ledger.realized_pnl == 0

def test_weighted_average_price_for_same_direction():
    ledger = PaperLedger("paper")

    ledger.apply_fill(
        fill(
            fill_id="1",
            side=OrderSide.BUY,
            quantity=1,
            price=100,
        )
    )
    ledger.apply_fill(
        fill(
            fill_id="2",
            side=OrderSide.BUY,
            quantity=3,
            price=110,
        )
    )

    position = ledger.positions()[0]

    assert position.quantity == 4
    assert position.average_price == 107.5


def test_partial_close_realizes_profit():
    ledger = PaperLedger("paper")

    ledger.apply_fill(
        fill(
            fill_id="1",
            side=OrderSide.BUY,
            quantity=4,
            price=100,
        )
    )
    ledger.apply_fill(
        fill(
            fill_id="2",
            side=OrderSide.SELL,
            quantity=1,
            price=110,
        )
    )

    position = ledger.positions()[0]

    assert position.quantity == 3
    assert position.average_price == 100
    assert ledger.realized_pnl == 10
    assert ledger.balance == 1010

def test_full_close_removes_position():
    ledger = PaperLedger("paper")

    ledger.apply_fill(
        fill(
            fill_id="1",
            side=OrderSide.BUY,
            quantity=2,
            price=100,
        )
    )
    ledger.apply_fill(
        fill(
            fill_id="2",
            side=OrderSide.SELL,
            quantity=2,
            price=95,
        )
    )

    assert ledger.positions() == ()
    assert ledger.realized_pnl == -10
    assert ledger.balance == 990


def test_position_flip_resets_average_price():
    ledger = PaperLedger("paper")

    ledger.apply_fill(
        fill(
            fill_id="1",
            side=OrderSide.BUY,
            quantity=2,
            price=100,
        )
    )
    ledger.apply_fill(
        fill(
            fill_id="2",
            side=OrderSide.SELL,
            quantity=5,
            price=110,
        )
    )

    position = ledger.positions()[0]

    assert position.side is OrderSide.SELL
    assert position.quantity == 3
    assert position.average_price == 110
    assert ledger.realized_pnl == 20

def test_unrealized_pnl_and_equity():
    ledger = PaperLedger(
        "paper",
        starting_balance=1000,
    )

    ledger.apply_fill(
        fill(
            fill_id="1",
            side=OrderSide.BUY,
            quantity=2,
            price=100,
        )
    )

    ledger.update_marks(
        {"EURUSD": 110},
        as_of=datetime.now(timezone.utc),
    )

    position = ledger.positions()[0]

    assert position.unrealized_pnl == 20
    assert ledger.unrealized_pnl == 20
    assert ledger.equity == 1020


def test_duplicate_fill_is_ignored():
    ledger = PaperLedger("paper")

    first = fill(
        fill_id="1",
        side=OrderSide.BUY,
        quantity=1,
        price=100,
    )

    assert ledger.apply_fill(first) is True
    assert ledger.apply_fill(first) is False

    assert len(ledger.fills) == 1


def test_account_snapshot():
    ledger = PaperLedger(
        "paper",
        starting_balance=1000,
    )

    snapshot = ledger.account_snapshot()

    assert snapshot.balance == 1000
    assert snapshot.equity == 1000
    assert snapshot.available_funds == 1000
    assert snapshot.currency == "USD"