"""Market data provider interface.

Supports both historical (REST) and real-time (WebSocket) data feeds.
Initial implementation targets Zerodha Kite; abstract base allows
other providers (e.g., NSE TBT, TrueData) to be swapped in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, AsyncIterator


class DataFeed(str, Enum):
    HISTORICAL = "HISTORICAL"
    REALTIME = "REALTIME"


class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    FUTURES = "FUTURES"
    OPTIONS_CE = "OPTIONS_CE"
    OPTIONS_PE = "OPTIONS_PE"


@dataclass(frozen=True)
class Instrument:
    instrument_token: int
    symbol: str
    name: str
    exchange: str
    instrument_type: InstrumentType
    expiry: datetime | None = None
    strike: Decimal = Decimal("0")
    lot_size: int = 1


@dataclass(frozen=True)
class OHLCV:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True)
class Tick:
    instrument_token: int
    timestamp: datetime
    last_price: Decimal
    last_quantity: int
    volume: int
    average_price: Decimal
    ohlc: dict[str, Decimal] | None = None


@dataclass(frozen=True)
class Quote:
    instrument_token: int
    last_price: Decimal
    ohlc: OHLCV | None = None
    volume: int = 0


class MarketDataProvider(ABC):
    """Abstract market data provider."""

    @abstractmethod
    async def get_historical(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[OHLCV]:
        ...

    @abstractmethod
    async def get_quote(
        self, instrument_tokens: list[int]
    ) -> dict[int, Quote]:
        ...

    @abstractmethod
    async def subscribe(
        self, instrument_tokens: list[int]
    ) -> AsyncIterator[Tick]:
        ...

    @abstractmethod
    async def get_instruments(
        self, exchange: str = "NFO"
    ) -> list[Instrument]:
        ...
