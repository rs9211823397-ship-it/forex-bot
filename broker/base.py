from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


@dataclass
class BrokerOrder:
    symbol: str
    side: str
    quantity: float
    entry: float
    stop_loss: float
    take_profit: float
    order_id: str = field(default_factory=lambda: uuid4().hex)
    status: OrderStatus = OrderStatus.PENDING
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    broker_reference: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Broker(ABC):
    @abstractmethod
    def place_order(self, order: BrokerOrder) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    def close_order(self, order_id: str, exit_price: float) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, order_id: str) -> BrokerOrder:
        raise NotImplementedError

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        raise NotImplementedError
