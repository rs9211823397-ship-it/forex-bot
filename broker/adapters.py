"""Fail-closed placeholders for future live broker integrations."""

from execution.models import OrderRequest

from broker.contracts import (
    BrokerFillSnapshot,
    BrokerHealth,
    BrokerOrderSnapshot,
    ExecutionUnavailableError,
)


class _DisabledLiveAdapter:
    """Base for adapters that intentionally have no live implementation."""

    is_live = False

    def __init__(self, reason: str | None = None):
        self._reason = reason or (
            "Live connectivity is not installed; execution is disabled"
        )

    def health(self) -> BrokerHealth:
        return BrokerHealth(
            adapter=self.name,
            ready=False,
            reason=self._reason,
        )

    def _unavailable(self):
        raise ExecutionUnavailableError(f"{self.name}: {self._reason}")

    def submit_order(self, account_id: str, request: OrderRequest):
        del account_id, request
        self._unavailable()

    def cancel_order(self, account_id: str, order_id: str):
        del account_id, order_id
        self._unavailable()

    def orders(self, account_id: str):
        del account_id
        self._unavailable()

    def fills(self, account_id: str):
        del account_id
        self._unavailable()

    def positions(self, account_id: str):
        del account_id
        self._unavailable()

    def account_snapshot(self, account_id: str):
        del account_id
        self._unavailable()


class MT5Adapter(_DisabledLiveAdapter):
    """MT5 interface placeholder; it never imports or contacts MT5."""

    name = "MT5"


class ExchangeAdapter(_DisabledLiveAdapter):
    """Crypto exchange placeholder; it never imports an exchange SDK."""

    name = "EXCHANGE"


class PaperAdapter:
    """BrokerAdapter implementation backed by BrokerSimulator."""

    name = "PAPER"
    is_live = False

    def __init__(self, simulator):
        from execution.simulation import BrokerSimulator

        if not isinstance(simulator, BrokerSimulator):
            raise TypeError("simulator must be a BrokerSimulator instance")

        self._simulator = simulator
        self._account_id = None

    def health(self):
        return BrokerHealth(
            adapter=self.name,
            ready=True,
            reason="Paper execution simulator is ready",
        )

    def submit_order(self, account_id: str, request: OrderRequest):
        account = self._bind_account(account_id)
        snapshot = self._simulator.submit(request)
        return self._order_snapshot(account, snapshot)

    def cancel_order(self, account_id: str, order_id: str):
        from datetime import datetime, timezone

        account = self._bind_account(account_id)
        snapshot = self._simulator.cancel(
            order_id,
            datetime.now(timezone.utc),
        )
        return self._order_snapshot(account, snapshot)

    def orders(self, account_id: str):
        account = self._bind_account(account_id)
        return tuple(
            self._order_snapshot(account, snapshot)
            for snapshot in self._simulator.orders
        )

    def fills(self, account_id: str):
        account = self._bind_account(account_id)
        return tuple(
            BrokerFillSnapshot(
                fill_id=fill.fill_id,
                order_id=fill.order_id,
                account_id=account,
                symbol=fill.symbol,
                side=fill.side,
                quantity=fill.quantity,
                price=fill.price,
                commission=fill.commission,
                fill_time=fill.fill_time,
            )
            for fill in self._simulator.fills
        )

    def positions(self, account_id: str):
        self._bind_account(account_id)
        return ()

    def account_snapshot(self, account_id: str):
        self._bind_account(account_id)
        raise ExecutionUnavailableError(
            "PAPER: account ledger is not implemented"
        )

    def _bind_account(self, account_id: str) -> str:
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("account_id must be a non-empty string")

        resolved = account_id.strip()

        if self._account_id is None:
            self._account_id = resolved
        elif self._account_id != resolved:
            raise ValueError(
                "PaperAdapter instance is already bound to another account"
            )

        return resolved

    @staticmethod
    def _order_snapshot(account_id, snapshot):
        return BrokerOrderSnapshot(
            order_id=snapshot.order_id,
            client_order_id=snapshot.request.client_order_id,
            account_id=account_id,
            symbol=snapshot.request.symbol,
            side=snapshot.request.side,
            quantity=snapshot.request.quantity,
            filled_quantity=snapshot.filled_quantity,
            state=snapshot.state.value,
            updated_time=snapshot.updated_time,
        )

