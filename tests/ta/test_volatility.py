"""Tests for src/ta/volatility.py — volatility analysis."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.data.providers import OHLCV
from src.ta.volatility import (
    historical_volatility,
    iv_percentile,
    iv_rank,
    iv_surface_point,
    parkinson_volatility,
)


def _candle(
    day: int,
    close: str,
    high: str | None = None,
    low: str | None = None,
) -> OHLCV:
    c = Decimal(close)
    h = Decimal(high) if high else c + Decimal("5")
    lo = Decimal(low) if low else c - Decimal("5")
    return OHLCV(
        timestamp=datetime(2025, 6, day, 9, 15, tzinfo=UTC),
        open=c - Decimal("2"),
        high=h,
        low=lo,
        close=c,
        volume=1000,
    )


class TestHistoricalVolatility:
    def test_returns_none_for_insufficient_data(self) -> None:
        candles = [_candle(1, "100")]
        result = historical_volatility(candles, 20)
        assert all(v is None for v in result)

    def test_produces_positive_vol(self) -> None:
        candles = [_candle(i, str(100 + (i % 5) * 3)) for i in range(1, 25)]
        result = historical_volatility(candles, 10)
        non_none = [v for v in result if v is not None]
        assert len(non_none) > 0
        assert all(v > Decimal("0") for v in non_none)

    def test_constant_price_zero_vol(self) -> None:
        candles = [_candle(i, "100") for i in range(1, 25)]
        result = historical_volatility(candles, 10)
        non_none = [v for v in result if v is not None]
        assert all(v == Decimal("0") for v in non_none)

    def test_invalid_period(self) -> None:
        with pytest.raises(ValueError):
            historical_volatility([_candle(1, "100")], 1)


class TestIVRank:
    def test_midpoint_when_no_history(self) -> None:
        assert iv_rank(Decimal("15"), []) == Decimal("0")

    def test_at_minimum(self) -> None:
        result = iv_rank(
            Decimal("10"),
            [Decimal("10"), Decimal("20"), Decimal("30")],
        )
        assert result == Decimal("0")

    def test_at_maximum(self) -> None:
        result = iv_rank(
            Decimal("30"),
            [Decimal("10"), Decimal("20"), Decimal("30")],
        )
        assert result == Decimal("100")

    def test_midpoint_when_all_same(self) -> None:
        result = iv_rank(
            Decimal("15"),
            [Decimal("15"), Decimal("15"), Decimal("15")],
        )
        assert result == Decimal("50")


class TestIVPercentile:
    def test_empty_history(self) -> None:
        assert iv_percentile(Decimal("15"), []) == Decimal("0")

    def test_all_below(self) -> None:
        result = iv_percentile(
            Decimal("30"),
            [Decimal("10"), Decimal("15"), Decimal("20")],
        )
        assert result == Decimal("100")

    def test_none_below(self) -> None:
        result = iv_percentile(
            Decimal("5"),
            [Decimal("10"), Decimal("15"), Decimal("20")],
        )
        assert result == Decimal("0")

    def test_partial(self) -> None:
        result = iv_percentile(
            Decimal("15"),
            [Decimal("10"), Decimal("12"), Decimal("20")],
        )
        assert result == Decimal("2") / Decimal("3") * Decimal("100")


class TestIVSurfacePoint:
    def test_atm_returns_atm_iv(self) -> None:
        result = iv_surface_point(
            Decimal("24000"),
            Decimal("15"),
            Decimal("24000"),
        )
        assert result == Decimal("15")

    def test_otm_higher_iv(self) -> None:
        atm_iv = iv_surface_point(
            Decimal("24000"),
            Decimal("15"),
            Decimal("24000"),
        )
        otm_iv = iv_surface_point(
            Decimal("25000"),
            Decimal("15"),
            Decimal("24000"),
        )
        assert otm_iv > atm_iv

    def test_zero_spot_returns_atm_iv(self) -> None:
        result = iv_surface_point(
            Decimal("24000"),
            Decimal("15"),
            Decimal("0"),
        )
        assert result == Decimal("15")


class TestParkinsonVolatility:
    def test_returns_none_for_insufficient_data(self) -> None:
        result = parkinson_volatility([], 20)
        assert result == []

    def test_produces_positive_vol(self) -> None:
        candles = [_candle(i, "100", "108", "92") for i in range(1, 25)]
        result = parkinson_volatility(candles, 10)
        non_none = [v for v in result if v is not None]
        assert len(non_none) > 0
        assert all(v > Decimal("0") for v in non_none)
