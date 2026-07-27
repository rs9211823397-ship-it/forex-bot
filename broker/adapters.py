"""Fail-closed placeholders for future live broker integrations."""

from execution.models import OrderRequest

from broker.contracts import BrokerHealth, ExecutionUnavailableError


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
