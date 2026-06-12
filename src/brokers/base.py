"""Abstract broker interface for order execution.

Zerodha Kite is the initial implementation.  The abstract base ensures
future brokers (e.g., Angel One, Upstox) can be swapped in cleanly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class ProductType(StrEnum):
    MIS = "MIS"
    NRML = "NRML"
    CNC = "CNC"


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class BrokerOrder:
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    price: Decimal
    trigger_price: Decimal
    product: ProductType
    tag: str


@dataclass(frozen=True)
class BrokerOrderResult:
    order_id: str
    status: OrderStatus
    message: str
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class Position:
    symbol: str
    segment: str
    quantity: int
    average_price: Decimal
    current_price: Decimal
    pnl: Decimal
    product: ProductType


@dataclass(frozen=True)
class MarginInfo:
    available: Decimal
    used: Decimal
    total: Decimal


class BrokerInterface(ABC):
    """Abstract broker — all concrete brokers must implement this."""

    @abstractmethod
    async def place_order(self, order: BrokerOrder) -> BrokerOrderResult: ...

    @abstractmethod
    async def cancel_order(
        self, order_id: str, segment: str = ""
    ) -> BrokerOrderResult: ...

    @abstractmethod
    async def cancel_all_orders(self) -> list[BrokerOrderResult]: ...

    @abstractmethod
    async def get_orders(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def get_margins(self) -> MarginInfo: ...

    @abstractmethod
    async def authenticate(self) -> str: ...

    @abstractmethod
    async def is_connected(self) -> bool: ...
