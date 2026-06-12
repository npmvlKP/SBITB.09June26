"""Tests for src/data/zerodha_provider.py — Zerodha MarketDataProvider."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.data.providers import InstrumentType
from src.data.zerodha_provider import ZerodhaDataProvider


@pytest.fixture
def mock_adapter() -> AsyncMock:
    adapter = AsyncMock()
    adapter._kite = MagicMock()
    adapter._kite.instruments.return_value = [
        {
            "instrument_token": 12345,
            "tradingsymbol": "NIFTY25JUNFUT",
            "name": "NIFTY 50",
            "exchange": "NFO",
            "instrument_type": "FUT",
            "expiry": "2025-06-26",
            "strike": 0,
            "lot_size": 25,
        },
        {
            "instrument_token": 12346,
            "tradingsymbol": "NIFTY25JUN24000CE",
            "name": "NIFTY 50",
            "exchange": "NFO",
            "instrument_type": "CE",
            "expiry": "2025-06-26",
            "strike": 24000,
            "lot_size": 25,
        },
        {
            "instrument_token": 12347,
            "tradingsymbol": "NIFTY25JUN24000PE",
            "name": "NIFTY 50",
            "exchange": "NFO",
            "instrument_type": "PE",
            "expiry": "2025-06-26",
            "strike": 24000,
            "lot_size": 25,
        },
        {
            "instrument_token": 12348,
            "tradingsymbol": "RELIANCE",
            "name": "RELIANCE IND",
            "exchange": "NSE",
            "instrument_type": "EQ",
            "expiry": None,
            "strike": 0,
            "lot_size": 1,
        },
    ]
    return adapter


@pytest.fixture
def provider(mock_adapter: AsyncMock) -> ZerodhaDataProvider:
    return ZerodhaDataProvider(mock_adapter)


class TestGetHistorical:
    @pytest.mark.asyncio
    async def test_fetches_and_converts(
        self, provider: ZerodhaDataProvider, mock_adapter: AsyncMock
    ) -> None:
        mock_adapter.get_historical_data.return_value = [
            {
                "date": datetime(2025, 6, 25, 9, 15, tzinfo=UTC),
                "open": Decimal("24000"),
                "high": Decimal("24100"),
                "low": Decimal("23950"),
                "close": Decimal("24050"),
                "volume": 1000000,
            },
        ]
        result = await provider.get_historical(
            instrument_token=12345,
            from_date=datetime(2025, 6, 25),
            to_date=datetime(2025, 6, 26),
            interval="day",
        )
        assert len(result) == 1
        assert result[0].close == Decimal("24050")
        assert result[0].volume == 1000000

    @pytest.mark.asyncio
    async def test_skips_candles_without_date(
        self, provider: ZerodhaDataProvider, mock_adapter: AsyncMock
    ) -> None:
        mock_adapter.get_historical_data.return_value = [
            {"open": 100, "high": 110, "low": 90, "close": 105, "volume": 100},
            {
                "date": datetime(2025, 6, 25, tzinfo=UTC),
                "open": Decimal("200"),
                "high": Decimal("210"),
                "low": Decimal("190"),
                "close": Decimal("205"),
                "volume": 200,
            },
        ]
        result = await provider.get_historical(
            12345, datetime(2025, 6, 25), datetime(2025, 6, 26)
        )
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_parses_iso_date_string(
        self, provider: ZerodhaDataProvider, mock_adapter: AsyncMock
    ) -> None:
        mock_adapter.get_historical_data.return_value = [
            {
                "date": "2025-06-25T09:15:00+00:00",
                "open": Decimal("100"),
                "high": Decimal("110"),
                "low": Decimal("90"),
                "close": Decimal("105"),
                "volume": 500,
            },
        ]
        result = await provider.get_historical(
            12345, datetime(2025, 6, 25), datetime(2025, 6, 26)
        )
        assert len(result) == 1
        assert isinstance(result[0].timestamp, datetime)


class TestGetQuote:
    @pytest.mark.asyncio
    async def test_fetches_ltp_as_quote(
        self, provider: ZerodhaDataProvider, mock_adapter: AsyncMock
    ) -> None:
        mock_adapter.get_ltp.return_value = {
            "NFO:12345": Decimal("24050"),
            "NFO:12346": Decimal("150"),
        }
        result = await provider.get_quote([12345, 12346])
        assert 12345 in result
        assert result[12345].last_price == Decimal("24050")
        assert result[12346].last_price == Decimal("150")

    @pytest.mark.asyncio
    async def test_missing_tokens_skipped(
        self, provider: ZerodhaDataProvider, mock_adapter: AsyncMock
    ) -> None:
        mock_adapter.get_ltp.return_value = {"NFO:12345": Decimal("100")}
        result = await provider.get_quote([12345, 99999])
        assert 12345 in result
        assert 99999 not in result


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self, provider: ZerodhaDataProvider) -> None:
        with pytest.raises(NotImplementedError, match="Ticker"):
            await provider.subscribe([12345])


class TestGetInstruments:
    @pytest.mark.asyncio
    async def test_fetches_and_maps_instruments(
        self, provider: ZerodhaDataProvider, mock_adapter: AsyncMock
    ) -> None:
        result = await provider.get_instruments("NFO")
        assert len(result) == 4
        assert result[0].instrument_token == 12345
        assert result[0].instrument_type == InstrumentType.FUTURES
        assert result[1].instrument_type == InstrumentType.OPTIONS_CE
        assert result[2].instrument_type == InstrumentType.OPTIONS_PE

    @pytest.mark.asyncio
    async def test_empty_when_not_connected(self, mock_adapter: AsyncMock) -> None:
        mock_adapter._kite = None
        provider = ZerodhaDataProvider(mock_adapter)
        result = await provider.get_instruments("NFO")
        assert result == []

    @pytest.mark.asyncio
    async def test_expiry_parsed(
        self, provider: ZerodhaDataProvider, mock_adapter: AsyncMock
    ) -> None:
        result = await provider.get_instruments("NFO")
        assert result[0].expiry is not None
