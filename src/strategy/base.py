"""Abstract strategy interface.

All strategies (rule-based and DRL) must implement this base.
Strategies produce signals; the execution layer handles order flow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class SignalDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class SignalStrength(StrEnum):
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


@dataclass(frozen=True)
class Signal:
    strategy_id: str
    symbol: str
    direction: SignalDirection
    strength: SignalStrength
    price: Decimal
    timestamp: datetime
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class StrategyConfig:
    strategy_id: str
    version: str
    params: dict[str, Any]
    allowed_symbols: list[str]
    max_position_size: int
    risk_per_trade: Decimal = Decimal("0.02")


@dataclass
class StrategyState:
    is_active: bool = False
    positions: dict[str, Decimal] | None = None
    pnl: Decimal = Decimal("0")
    trade_count: int = 0
    last_signal_time: datetime | None = None


class StrategyBase(ABC):
    """Abstract strategy — all strategies must implement this."""

    def __init__(self, config: StrategyConfig) -> None:
        self.config = config
        self.state = StrategyState(positions={})

    @abstractmethod
    async def generate_signal(
        self, market_data: dict[str, Any]
    ) -> Signal | None:
        ...

    @abstractmethod
    async def on_fill(
        self, symbol: str, qty: int, price: Decimal
    ) -> None:
        ...

    @abstractmethod
    async def on_stop(self) -> None:
        ...

    @abstractmethod
    def get_state(self) -> StrategyState:
        ...

    @property
    def strategy_id(self) -> str:
        return self.config.strategy_id

    @property
    def version(self) -> str:
        return self.config.version
