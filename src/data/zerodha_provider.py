"""Zerodha KiteConnect market data provider.

Concrete implementation of MarketDataProvider using Zerodha Kite REST API.
Handles historical candles, quotes, instrument master, and float↔Decimal conversion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from src.data.providers import (
    OHLCV,
    Instrument,
    InstrumentType,
    MarketDataProvider,
    Quote,
    Tick,
)

logger = structlog.get_logger(__name__)

_INSTRUMENT_TYPE_MAP: dict[str, InstrumentType] = {
    "EQ": InstrumentType.EQUITY,
    "FUT": InstrumentType.FUTURES,
    "CE": InstrumentType.OPTIONS_CE,
    "PE": InstrumentType.OPTIONS_PE,
}

_INTERVAL_MAP: dict[str, str] = {
    "minute": "minute",
    "3minute": "3minute",
    "5minute": "5minute",
    "15minute": "15minute",
    "30minute": "30minute",
    "60minute": "60minute",
    "day": "day",
    "week": "week",
    "month": "month",
}


class ZerodhaDataProvider(MarketDataProvider):
    """Zerodha KiteConnect data provider.

    Wraps ZerodhaAdapter to delegate REST calls, converting
    float→Decimal at the boundary.
    """

    def __init__(self, zerodha_adapter: Any) -> None:
        self._adapter = zerodha_adapter
        self._instruments_cache: dict[str, list[Instrument]] = {}
        self._instruments_cache_time: datetime | None = None

    async def get_historical(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[OHLCV]:
        """Fetch historical OHLCV candles via Zerodha REST API."""
        kite_interval = _INTERVAL_MAP.get(interval, interval)
        raw_candles = await self._adapter.get_historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=kite_interval,
        )
        result: list[OHLCV] = []
        for c in raw_candles:
            ts = c.get("date")
            if ts is None:
                continue
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            result.append(
                OHLCV(
                    timestamp=ts,
                    open=Decimal(str(c.get("open", 0))),
                    high=Decimal(str(c.get("high", 0))),
                    low=Decimal(str(c.get("low", 0))),
                    close=Decimal(str(c.get("close", 0))),
                    volume=int(c.get("volume", 0)),
                )
            )
        logger.info(
            "data.historical_fetched",
            token=instrument_token,
            interval=kite_interval,
            count=len(result),
        )
        return result

    async def get_quote(
        self,
        instrument_tokens: list[int],
    ) -> dict[int, Quote]:
        """Fetch quotes for given instrument tokens."""
        instruments_str = [f"NFO:{t}" for t in instrument_tokens]
        ltp_data = await self._adapter.get_ltp(instruments_str)
        quotes: dict[int, Quote] = {}
        for token in instrument_tokens:
            key = f"NFO:{token}"
            if key in ltp_data:
                quotes[token] = Quote(
                    instrument_token=token,
                    last_price=ltp_data[key],
                )
        return quotes

    async def subscribe(
        self,
        instrument_tokens: list[int],
    ) -> AsyncIterator[Tick]:
        """Subscribe not supported via REST — use Ticker for WebSocket."""
        raise NotImplementedError(
            "Real-time subscription requires WebSocket ticker. "
            "Use src.data.ticker.TickerManager instead."
        )

    async def get_instruments(
        self,
        exchange: str = "NFO",
    ) -> list[Instrument]:
        """Fetch and cache instrument master for an exchange."""
        if self._adapter._kite is None:  # noqa: SLF001
            logger.warning("data.adapter_not_connected")
            return []

        raw_instruments = self._adapter._kite.instruments(exchange=exchange)  # noqa: SLF001
        result: list[Instrument] = []
        for inst in raw_instruments:
            inst_type = _map_instrument_type(inst)
            if inst_type is None:
                continue
            expiry = inst.get("expiry")
            if expiry is not None and isinstance(expiry, str):
                try:
                    expiry = datetime.fromisoformat(expiry)
                except (ValueError, TypeError):
                    expiry = None
            result.append(
                Instrument(
                    instrument_token=inst.get("instrument_token", 0),
                    symbol=inst.get("tradingsymbol", ""),
                    name=inst.get("name", ""),
                    exchange=inst.get("exchange", exchange),
                    instrument_type=inst_type,
                    expiry=expiry,
                    strike=Decimal(str(inst.get("strike", 0))),
                    lot_size=inst.get("lot_size", 1),
                )
            )
        logger.info(
            "data.instruments_fetched",
            exchange=exchange,
            count=len(result),
        )
        return result


def _map_instrument_type(inst: dict[str, Any]) -> InstrumentType | None:
    """Map Zerodha instrument_type + instrument_type field to our enum."""
    raw = inst.get("instrument_type", "")
    if isinstance(raw, str):
        return _INSTRUMENT_TYPE_MAP.get(raw.upper())
    return None
