"""Tests for src/ta/indicators.py — technical indicators."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.data.providers import OHLCV
from src.ta.indicators import (
    atr,
    bollinger_bands,
    ema,
    macd,
    rsi,
    sma,
    vwap,
)


def _candle(
    day: int,
    close: str,
    high: str | None = None,
    low: str | None = None,
    open_price: str | None = None,
    volume: int = 1000,
) -> OHLCV:
    c = Decimal(close)
    h = Decimal(high) if high else c + Decimal("5")
    lo = Decimal(low) if low else c - Decimal("5")
    o = Decimal(open_price) if open_price else c - Decimal("2")
    return OHLCV(
        timestamp=datetime(2025, 6, day, 9, 15, tzinfo=UTC),
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=volume,
    )


class TestSMA:
    def test_period_3(self) -> None:
        candles = [
            _candle(1, "10"),
            _candle(2, "20"),
            _candle(3, "30"),
            _candle(4, "40"),
        ]
        result = sma(candles, 3)
        assert result[0] is None
        assert result[1] is None
        assert result[2] == Decimal("20")
        assert result[3] == Decimal("30")

    def test_insufficient_data(self) -> None:
        candles = [_candle(1, "100")]
        result = sma(candles, 5)
        assert all(v is None for v in result)

    def test_invalid_period(self) -> None:
        candles = [_candle(1, "100")]
        with pytest.raises(ValueError):
            sma(candles, 0)


class TestEMA:
    def test_starts_with_sma(self) -> None:
        candles = [_candle(i, str(100 + i * 10)) for i in range(1, 11)]
        result = ema(candles, 5)
        assert result[:4] == [None] * 4
        assert result[4] is not None
        expected_sma = sum(Decimal(str(100 + i * 10)) for i in range(1, 6)) / Decimal(5)
        assert abs(result[4] - expected_sma) < Decimal("0.01")

    def test_exponential_weighting(self) -> None:
        candles = [_candle(1, "100"), _candle(2, "200"), _candle(3, "300")]
        result = ema(candles, 2)
        assert result[0] is None
        assert result[1] is not None
        assert result[2] is not None


class TestRSI:
    def test_all_gains_high_rsi(self) -> None:
        candles = [_candle(i, str(100 + i * 10)) for i in range(1, 20)]
        result = rsi(candles, 14)
        assert result[-1] is not None
        assert result[-1] > Decimal("80")

    def test_all_losses_low_rsi(self) -> None:
        candles = [_candle(i, str(300 - i * 10)) for i in range(1, 20)]
        result = rsi(candles, 14)
        assert result[-1] is not None
        assert result[-1] < Decimal("20")

    def test_insufficient_data(self) -> None:
        candles = [_candle(1, "100"), _candle(2, "110")]
        result = rsi(candles, 14)
        assert all(v is None for v in result)


class TestATR:
    def test_basic_calculation(self) -> None:
        candles = [
            _candle(1, "100", "108", "92"),
            _candle(2, "105", "115", "98"),
            _candle(3, "110", "120", "100"),
            _candle(4, "115", "125", "105"),
        ]
        result = atr(candles, 2)
        assert result[0] is None
        assert result[2] is not None
        assert result[3] is not None

    def test_single_candle(self) -> None:
        candles = [_candle(1, "100")]
        result = atr(candles, 14)
        assert all(v is None for v in result)


class TestVWAP:
    def test_basic_vwap(self) -> None:
        candles = [
            _candle(1, "100", "105", "95", "98", 1000),
            _candle(2, "110", "115", "105", "108", 2000),
        ]
        result = vwap(candles)
        assert result[0] is not None
        assert result[1] is not None
        assert result[0] < result[1]

    def test_zero_volume(self) -> None:
        candles = [_candle(1, "100", volume=0)]
        result = vwap(candles)
        assert result[0] is None


class TestBollingerBands:
    def test_basic_bands(self) -> None:
        candles = [_candle(i, str(100 + i)) for i in range(1, 25)]
        result = bollinger_bands(candles, 20, 2)
        assert result[18] is None
        assert result[19] is not None
        middle, upper, lower = result[19]
        assert upper > middle > lower

    def test_constant_price_bands_collapse(self) -> None:
        candles = [_candle(i, "100") for i in range(1, 25)]
        result = bollinger_bands(candles, 20, 2)
        middle, upper, lower = result[19]
        assert upper == middle
        assert lower == middle


class TestMACD:
    def test_returns_none_for_insufficient_data(self) -> None:
        candles = [_candle(i, "100") for i in range(1, 5)]
        result = macd(candles, 12, 26, 9)
        assert all(v is None for v in result)

    def test_produces_values_with_enough_data(self) -> None:
        candles = [_candle((i % 28) + 1, str(100 + i * 2)) for i in range(1, 50)]
        result = macd(candles, 12, 26, 9)
        non_none = [v for v in result if v is not None]
        assert len(non_none) > 0
