"""Technical indicators for F&O strategy evaluation.

All calculations use Decimal for financial precision.
Indicators are pure functions operating on OHLCV lists.
"""

from __future__ import annotations

from decimal import Decimal
from math import sqrt

from src.data.providers import OHLCV

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")
_HUNDRED = Decimal("100")


def sma(candles: list[OHLCV], period: int) -> list[Decimal | None]:
    """Simple Moving Average of close prices.

    Returns list aligned with input; None where insufficient data.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    result: list[Decimal | None] = []
    closes = [c.close for c in candles]
    for i in range(len(candles)):
        if i < period - 1:
            result.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            result.append(sum(window) / Decimal(period))
    return result


def ema(candles: list[OHLCV], period: int) -> list[Decimal | None]:
    """Exponential Moving Average of close prices.

    Uses standard multiplier: 2 / (period + 1).
    First EMA value = SMA of first `period` closes.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    closes = [c.close for c in candles]
    if len(closes) < period:
        return [None] * len(candles)
    multiplier = _TWO / Decimal(period + 1)
    result: list[Decimal | None] = []
    first_sma = sum(closes[:period]) / Decimal(period)
    result.extend([None] * (period - 1))
    result.append(first_sma)
    prev = first_sma
    for i in range(period, len(closes)):
        current = (closes[i] - prev) * multiplier + prev
        result.append(current)
        prev = current
    return result


def rsi(candles: list[OHLCV], period: int = 14) -> list[Decimal | None]:
    """Relative Strength Index.

    Uses Wilder's smoothing (exponential) for avg gain/loss.
    Returns 0-100 scale; None where insufficient data.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    closes = [c.close for c in candles]
    n = len(closes)
    if n < period + 1:
        return [None] * n
    result: list[Decimal | None] = [None] * period
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, _ZERO) for d in deltas[:period]]
    losses = [max(-d, _ZERO) for d in deltas[:period]]
    avg_gain = sum(gains) / Decimal(period)
    avg_loss = sum(losses) / Decimal(period)
    if avg_loss == _ZERO:
        result.append(_HUNDRED)
    else:
        rs = avg_gain / avg_loss
        result.append(_HUNDRED - _HUNDRED / (_ONE + rs))
    for i in range(period, len(deltas)):
        gain = max(deltas[i], _ZERO)
        loss = max(-deltas[i], _ZERO)
        avg_gain = (avg_gain * Decimal(period - 1) + gain) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + loss) / Decimal(period)
        if avg_loss == _ZERO:
            result.append(_HUNDRED)
        else:
            rs = avg_gain / avg_loss
            result.append(_HUNDRED - _HUNDRED / (_ONE + rs))
    return result


def atr(candles: list[OHLCV], period: int = 14) -> list[Decimal | None]:
    """Average True Range.

    Uses Wilder's smoothing. True Range = max(H-L, |H-prevC|, |L-prevC|).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(candles)
    if n < 2:
        return [None] * n
    result: list[Decimal | None] = [None]
    tr_values: list[Decimal] = []
    for i in range(1, n):
        high_low = candles[i].high - candles[i].low
        high_close = abs(candles[i].high - candles[i - 1].close)
        low_close = abs(candles[i].low - candles[i - 1].close)
        tr_values.append(max(high_low, high_close, low_close))
    if len(tr_values) < period:
        result.extend([None] * (len(tr_values)))
        return result
    first_atr = sum(tr_values[:period]) / Decimal(period)
    result.extend([None] * (period - 1))
    result.append(first_atr)
    prev_atr = first_atr
    for i in range(period, len(tr_values)):
        current = (prev_atr * Decimal(period - 1) + tr_values[i]) / Decimal(period)
        result.append(current)
        prev_atr = current
    return result


def vwap(candles: list[OHLCV]) -> list[Decimal | None]:
    """Volume Weighted Average Price (cumulative).

    Resets daily; caller should pass single-day candles.
    """
    result: list[Decimal | None] = []
    cum_volume = 0
    cum_tp_volume = _ZERO
    for c in candles:
        typical = (c.high + c.low + c.close) / _THREE
        tp_vol = typical * Decimal(c.volume)
        cum_tp_volume += tp_vol
        cum_volume += c.volume
        if cum_volume == 0:
            result.append(None)
        else:
            result.append(cum_tp_volume / Decimal(cum_volume))
    return result


def bollinger_bands(
    candles: list[OHLCV],
    period: int = 20,
    num_std: int = 2,
) -> list[tuple[Decimal, Decimal, Decimal] | None]:
    """Bollinger Bands (middle, upper, lower).

    Middle = SMA(period), bands = middle ± num_std * stdev.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    closes = [c.close for c in candles]
    n = len(candles)
    result: list[tuple[Decimal, Decimal, Decimal] | None] = []
    for i in range(n):
        if i < period - 1:
            result.append(None)
        else:
            window = closes[i - period + 1 : i + 1]
            middle = sum(window) / Decimal(period)
            variance = sum((c - middle) ** _TWO for c in window) / Decimal(period)
            std = Decimal(str(sqrt(float(variance))))
            upper = middle + Decimal(num_std) * std
            lower = middle - Decimal(num_std) * std
            result.append((middle, upper, lower))
    return result


def macd(
    candles: list[OHLCV],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> list[tuple[Decimal, Decimal, Decimal] | None]:
    """MACD (line, signal, histogram).

    MACD line = EMA(fast) - EMA(slow).
    Signal = EMA(signal_period) of MACD line.
    Histogram = MACD - Signal.
    """
    fast_ema = ema(candles, fast_period)
    slow_ema = ema(candles, slow_period)
    macd_line: list[Decimal | None] = []
    for f, s in zip(fast_ema, slow_ema, strict=False):
        if f is not None and s is not None:
            macd_line.append(f - s)
        else:
            macd_line.append(None)
    valid_macd: list[Decimal | None] = [v for v in macd_line if v is not None]
    first_valid_idx = next(
        (i for i, v in enumerate(macd_line) if v is not None),
        len(macd_line),
    )
    signal_values = _ema_from_values(
        valid_macd, signal_period, first_valid_idx, len(candles)
    )
    result: list[tuple[Decimal, Decimal, Decimal] | None] = []
    for i in range(len(candles)):
        ml = macd_line[i]
        sig = signal_values[i]
        if ml is not None and sig is not None:
            result.append((ml, sig, ml - sig))
        else:
            result.append(None)
    return result


_THREE = Decimal("3")


def _ema_from_values(
    values: list[Decimal | None],
    period: int,
    offset: int,
    total_length: int,
) -> list[Decimal | None]:
    """Compute EMA on a pre-extracted list of Decimal values."""
    if not values or len(values) < period:
        return [None] * total_length
    multiplier = _TWO / Decimal(period + 1)
    result: list[Decimal | None] = [None] * total_length
    first_sma = sum(v for v in values[:period] if v is not None) / Decimal(period)
    result[offset + period - 1] = first_sma
    prev = first_sma
    for i in range(period, len(values)):
        val = values[i]
        if val is None:
            continue
        current: Decimal = (val - prev) * multiplier + prev
        result[offset + i] = current
        prev = current
    return result
