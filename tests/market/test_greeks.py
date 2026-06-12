"""Tests for src/market/greeks.py — Black-Scholes Greeks."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.market.greeks import (
    all_greeks,
    delta,
    gamma,
    rho,
    theta,
    time_to_expiry_years,
    vega,
)

_SPOT = Decimal("24000")
_STRIKE = Decimal("24000")
_TTE = Decimal("0.083")  # ~1 month
_RATE = Decimal("0.065")  # RBI repo rate ~6.5%
_VOL = Decimal("0.15")  # 15% IV


class TestDelta:
    def test_atm_call_near_05(self) -> None:
        d = delta(_SPOT, _STRIKE, _TTE, _RATE, _VOL, is_call=True)
        assert Decimal("0.4") < d < Decimal("0.6")

    def test_atm_put_near_minus_05(self) -> None:
        d = delta(_SPOT, _STRIKE, _TTE, _RATE, _VOL, is_call=False)
        assert Decimal("-0.6") < d < Decimal("-0.4")

    def test_deep_itm_call_near_1(self) -> None:
        d = delta(
            Decimal("26000"),
            Decimal("24000"),
            _TTE,
            _RATE,
            _VOL,
            is_call=True,
        )
        assert d > Decimal("0.9")

    def test_zero_tte_returns_atm_delta(self) -> None:
        d = delta(_SPOT, _STRIKE, Decimal("0"), _RATE, _VOL)
        assert d == Decimal("0.5")


class TestGamma:
    def test_atm_positive(self) -> None:
        g = gamma(_SPOT, _STRIKE, _TTE, _RATE, _VOL)
        assert g > Decimal("0")

    def test_zero_tte_returns_zero(self) -> None:
        g = gamma(_SPOT, _STRIKE, Decimal("0"), _RATE, _VOL)
        assert g == Decimal("0")


class TestTheta:
    def test_long_option_negative(self) -> None:
        t = theta(_SPOT, _STRIKE, _TTE, _RATE, _VOL, is_call=True)
        assert t < Decimal("0")

    def test_put_theta(self) -> None:
        t = theta(_SPOT, _STRIKE, _TTE, _RATE, _VOL, is_call=False)
        assert t < Decimal("0")

    def test_zero_tte(self) -> None:
        t = theta(_SPOT, _STRIKE, Decimal("0"), _RATE, _VOL)
        assert t == Decimal("0")


class TestVega:
    def test_atm_positive(self) -> None:
        v = vega(_SPOT, _STRIKE, _TTE, _RATE, _VOL)
        assert v > Decimal("0")

    def test_zero_tte(self) -> None:
        v = vega(_SPOT, _STRIKE, Decimal("0"), _RATE, _VOL)
        assert v == Decimal("0")


class TestRho:
    def test_call_rho_positive(self) -> None:
        r = rho(_SPOT, _STRIKE, _TTE, _RATE, _VOL, is_call=True)
        assert r > Decimal("0")

    def test_put_rho_negative(self) -> None:
        r = rho(_SPOT, _STRIKE, _TTE, _RATE, _VOL, is_call=False)
        assert r < Decimal("0")


class TestTimeToExpiry:
    def test_future_expiry(self) -> None:
        now = datetime(2025, 6, 25, tzinfo=UTC)
        expiry = datetime(2025, 6, 26, 15, 30, tzinfo=UTC)
        result = time_to_expiry_years(expiry, now)
        assert result > Decimal("0")
        assert result < Decimal("1")

    def test_past_expiry_returns_zero(self) -> None:
        now = datetime(2025, 6, 27, tzinfo=UTC)
        expiry = datetime(2025, 6, 26, 15, 30, tzinfo=UTC)
        result = time_to_expiry_years(expiry, now)
        assert result == Decimal("0")

    def test_naive_datetime_handled(self) -> None:
        now = datetime(2025, 6, 25)
        expiry = datetime(2025, 6, 26)
        result = time_to_expiry_years(expiry, now)
        assert result > Decimal("0")


class TestAllGreeks:
    def test_returns_all_keys(self) -> None:
        result = all_greeks(_SPOT, _STRIKE, _TTE, _RATE, _VOL, is_call=True)
        assert "delta" in result
        assert "gamma" in result
        assert "theta" in result
        assert "vega" in result
        assert "rho" in result

    def test_put_delta_negative(self) -> None:
        result = all_greeks(_SPOT, _STRIKE, _TTE, _RATE, _VOL, is_call=False)
        assert result["delta"] < Decimal("0")
