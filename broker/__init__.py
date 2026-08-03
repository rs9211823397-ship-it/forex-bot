"""Broker-neutral production execution contracts.

The package deliberately contains no live connectivity.  Concrete live
adapters must be explicitly installed and enabled by a deployment.
"""

from broker.adapters import ExchangeAdapter, MT5Adapter
from broker.contracts import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerFillSnapshot,
    BrokerHealth,
    BrokerOrderSnapshot,
    ExecutionUnavailableError,
    PositionSnapshot,
)
from broker.reconciliation import (
    ReconciliationIssue,
    ReconciliationReport,
    reconcile_orders,
)

__all__ = [
    "AccountSnapshot",
    "BrokerAdapter",
    "BrokerFillSnapshot",
    "BrokerHealth",
    "BrokerOrderSnapshot",
    "ExchangeAdapter",
    "ExecutionUnavailableError",
    "MT5Adapter",
    "PositionSnapshot",
    "ReconciliationIssue",
    "ReconciliationReport",
    "reconcile_orders",
]
