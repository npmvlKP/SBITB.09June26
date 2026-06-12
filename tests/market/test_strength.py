"""Tests for src/market/strength.py — market strength indicators."""

from __future__ import annotations

from decimal import Decimal

from src.market.strength import (
    MarketBias,
    analyze_oi,
    index_breadth,
    interpret_vix,
    pcr,
    support_resistance_from_oi,
)


class TestPCR:
    def test_neutral_range(self) -> None:
        result = pcr(
            call_oi=Decimal("100000"),
            put_oi=Decimal("90000"),
        )
        assert result.bias == MarketBias.NEUTRAL
        assert result.pcr == Decimal("0.9")

    def test_bullish_high_pcr(self) -> None:
        result = pcr(
            call_oi=Decimal("100000"),
            put_oi=Decimal("130000"),
        )
        assert result.bias == MarketBias.BULLISH
        assert result.pcr == Decimal("1.3")

    def test_bearish_low_pcr(self) -> None:
        result = pcr(
            call_oi=Decimal("100000"),
            put_oi=Decimal("60000"),
        )
        assert result.bias == MarketBias.BEARISH

    def test_zero_call_oi(self) -> None:
        result = pcr(
            call_oi=Decimal("0"),
            put_oi=Decimal("100000"),
        )
        assert result.bias == MarketBias.NEUTRAL
        assert result.pcr == Decimal("0")

    def test_volume_based_pcr(self) -> None:
        result = pcr(
            call_oi=Decimal("100000"),
            put_oi=Decimal("100000"),
            call_volume=Decimal("50000"),
            put_volume=Decimal("70000"),
            use_volume=True,
        )
        assert result.pcr == Decimal("1.4")
        assert result.bias == MarketBias.BULLISH


class TestVIXInterpretation:
    def test_low_vix(self) -> None:
        result = interpret_vix(Decimal("10"))
        assert result.regime == "LOW_VOLATILITY"
        assert result.bias == MarketBias.BULLISH

    def test_normal_vix(self) -> None:
        result = interpret_vix(Decimal("15"))
        assert result.regime == "NORMAL"
        assert result.bias == MarketBias.NEUTRAL

    def test_elevated_vix(self) -> None:
        result = interpret_vix(Decimal("20"))
        assert result.regime == "ELEVATED"
        assert result.bias == MarketBias.BEARISH

    def test_high_fear_vix(self) -> None:
        result = interpret_vix(Decimal("30"))
        assert result.regime == "HIGH_FEAR"
        assert result.bias == MarketBias.BULLISH

    def test_boundary_at_12(self) -> None:
        result = interpret_vix(Decimal("12"))
        assert result.regime == "NORMAL"

    def test_boundary_at_18(self) -> None:
        result = interpret_vix(Decimal("18"))
        assert result.regime == "ELEVATED"


class TestAnalyzeOI:
    def test_long_buildup(self) -> None:
        result = analyze_oi(
            "NIFTY",
            Decimal("2000000"),
            Decimal("1500000"),
            Decimal("24500"),
            Decimal("24000"),
        )
        assert result.interpretation == "LONG_BUILDUP"
        assert result.oi_change == Decimal("500000")
        assert result.price_change == Decimal("500")

    def test_short_buildup(self) -> None:
        result = analyze_oi(
            "NIFTY",
            Decimal("2000000"),
            Decimal("1500000"),
            Decimal("23500"),
            Decimal("24000"),
        )
        assert result.interpretation == "SHORT_BUILDUP"

    def test_short_covering(self) -> None:
        result = analyze_oi(
            "NIFTY",
            Decimal("1000000"),
            Decimal("1500000"),
            Decimal("24500"),
            Decimal("24000"),
        )
        assert result.interpretation == "SHORT_COVERING"

    def test_long_unwinding(self) -> None:
        result = analyze_oi(
            "NIFTY",
            Decimal("1000000"),
            Decimal("1500000"),
            Decimal("23500"),
            Decimal("24000"),
        )
        assert result.interpretation == "LONG_UNWINDING"

    def test_oi_change_pct(self) -> None:
        result = analyze_oi(
            "NIFTY",
            Decimal("1500000"),
            Decimal("1000000"),
            Decimal("24500"),
            Decimal("24000"),
        )
        assert result.oi_change_pct == Decimal("50")

    def test_zero_prev_oi(self) -> None:
        result = analyze_oi(
            "NIFTY",
            Decimal("1000"),
            Decimal("0"),
            Decimal("24500"),
            Decimal("24000"),
        )
        assert result.oi_change_pct == Decimal("0")


class TestIndexBreadth:
    def test_bullish_breadth(self) -> None:
        result = index_breadth(advances=30, declines=10)
        assert result.bias == MarketBias.BULLISH
        assert result.advance_decline_ratio == Decimal("3")

    def test_bearish_breadth(self) -> None:
        result = index_breadth(advances=5, declines=30)
        assert result.bias == MarketBias.BEARISH

    def test_neutral_breadth(self) -> None:
        result = index_breadth(advances=15, declines=15)
        assert result.bias == MarketBias.NEUTRAL

    def test_zero_declines(self) -> None:
        result = index_breadth(advances=10, declines=0)
        assert result.advance_decline_ratio == Decimal("10")


class TestSupportResistanceFromOI:
    def test_returns_top_n(self) -> None:
        data = {
            Decimal("23500"): Decimal("50000"),
            Decimal("24000"): Decimal("200000"),
            Decimal("24500"): Decimal("150000"),
            Decimal("25000"): Decimal("100000"),
        }
        result = support_resistance_from_oi(data, top_n=2)
        assert len(result) == 2
        assert result[0][0] == Decimal("24000")
        assert result[1][0] == Decimal("24500")

    def test_empty_data(self) -> None:
        result = support_resistance_from_oi({}, top_n=3)
        assert result == []
