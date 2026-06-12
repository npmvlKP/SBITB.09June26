"""Volatility analysis for Indian F&O markets.

Provides historical volatility, IV rank, IV percentile,
and simple IV surface estimation.
"""

from __future__ import annotations

from decimal import Decimal
from math import log as math_log
from math import sqrt

from src.data.providers import OHLCV

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")
_TRADING_DAYS_YEAR = Decimal("252")


def historical_volatility(
    candles: list[OHLCV],
    period: int = 20,
    annualize: bool = True,
) -> list[Decimal | None]:
    """Historical (realized) volatility from close-to-close returns.

    Returns standard deviation of log returns, optionally annualized.
    """
    if period <= 1:
        raise ValueError("period must be > 1")
    n = len(candles)
    if n < 2:
        return [None] * n
    log_returns: list[float] = []
    for i in range(1, n):
        if candles[i - 1].close > _ZERO and candles[i].close > _ZERO:
            lr = float(candles[i].close / candles[i - 1].close)
            if lr > 0:
                log_returns.append(__import__("math").log(lr))
            else:
                log_returns.append(0.0)
        else:
            log_returns.append(0.0)
    result: list[Decimal | None] = [None, None]
    for i in range(1, len(log_returns)):
        start = max(0, i - period + 1)
        window = log_returns[start : i + 1]
        if len(window) < 2:
            result.append(None)
            continue
        mean = sum(window) / len(window)
        variance = sum((r - mean) ** 2 for r in window) / len(window)
        vol = Decimal(str(sqrt(variance)))
        if annualize:
            vol = vol * Decimal(str(sqrt(float(_TRADING_DAYS_YEAR))))
        result.append(vol)
    return result


def iv_rank(
    current_iv: Decimal,
    iv_history: list[Decimal],
) -> Decimal:
    """IV Rank: percentile of current IV in historical range.

    IV Rank = (current - min) / (max - min) * 100
    If max == min, returns 50 (midpoint).
    """
    if not iv_history:
        return _ZERO
    min_iv = min(iv_history)
    max_iv = max(iv_history)
    if max_iv == min_iv:
        return Decimal("50")
    rank = (current_iv - min_iv) / (max_iv - min_iv) * _HUNDRED
    return max(_ZERO, min(_HUNDRED, rank))


def iv_percentile(
    current_iv: Decimal,
    iv_history: list[Decimal],
) -> Decimal:
    """IV Percentile: % of historical IVs below current IV."""
    if not iv_history:
        return _ZERO
    below = sum(1 for iv in iv_history if iv < current_iv)
    return Decimal(below) / Decimal(len(iv_history)) * _HUNDRED


def iv_surface_point(
    strike: Decimal,
    atm_iv: Decimal,
    spot: Decimal,
    skew_factor: Decimal = Decimal("0.1"),
) -> Decimal:
    """Simple IV surface estimation using volatility skew.

    Approximates IV at a given strike based on distance from ATM.
    skew_factor controls how much IV increases for OTM options.
    IV(strike) = ATM_IV * (1 + skew_factor * |strike/spot - 1|)
    """
    if spot <= _ZERO:
        return atm_iv
    moneyness = strike / spot - _ONE
    skew = skew_factor * abs(moneyness)
    return atm_iv * (_ONE + skew)


def parkinson_volatility(
    candles: list[OHLCV],
    period: int = 20,
    annualize: bool = True,
) -> list[Decimal | None]:
    """Parkinson volatility estimator using H/L range.

    More efficient than close-to-close for intraday data.
    sigma = sqrt(1/(4*n*ln2)) * sum(ln(H/L)^2)
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(candles)
    if n < 1:
        return []
    factor = Decimal(str(1 / (4 * math_log(2))))
    result: list[Decimal | None] = []
    for i in range(n):
        if i < period - 1:
            result.append(None)
        else:
            window = candles[i - period + 1 : i + 1]
            sum_sq = _ZERO
            for c in window:
                if c.low > _ZERO and c.high > _ZERO:
                    ratio = float(c.high / c.low)
                    if ratio > 0:
                        sum_sq += Decimal(str(math_log(ratio) ** 2))
            vol = Decimal(str(sqrt(float(factor * sum_sq / Decimal(period)))))
            if annualize:
                vol = vol * Decimal(str(sqrt(float(_TRADING_DAYS_YEAR))))
            result.append(vol)
    return result
