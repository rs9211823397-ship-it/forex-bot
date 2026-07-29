"""Execution backend router for paper and live broker modes."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from execution.models import OrderRequest, OrderSnapshot
from execution.simulation import BrokerSimulator


@runtime_checkable
class ExecutionBackend(Protocol):
    """Minimal execution interface used by the trading engine."""

    def submit(self, request: OrderRequest) -> OrderSnapshot:
        ...


class ExecutionRouter:
    """Route orders to the configured execution backend."""

    def __init__(self, backend: ExecutionBackend):
        if not isinstance(backend, ExecutionBackend):
            raise TypeError("backend must implement ExecutionBackend")

        self._backend = backend

    @property
    def backend(self) -> ExecutionBackend:
        return self._backend

    def submit(self, request: OrderRequest) -> OrderSnapshot:
        return self._backend.submit(request)


def create_paper_router(simulator: BrokerSimulator) -> ExecutionRouter:
    """Create an execution router backed by BrokerSimulator."""

    return ExecutionRouter(simulator)
