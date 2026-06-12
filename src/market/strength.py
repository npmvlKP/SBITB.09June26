"""Market strength indicators for Indian F&O markets.

Includes: Put-Call Ratio (PCR), India VIX interpretation,
Open Interest analysis, and index breadth.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

import structlog

logger = structlog.get_logger(__name__)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


class MarketBias(StrEnum):
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"


@dataclass(frozen=True)
class PCRResult:
    pcr: Decimal
    bias: MarketBias
    call_oi: Decimal
    put_oi: Decimal


@dataclass(frozen=True)
class VIXInterpretation:
    vix_value: Decimal
    regime: str
    bias: MarketBias
    description: str


@dataclass(frozen=True)
class OIAnalysis:
    symbol: str
    current_oi: Decimal
    prev_oi: Decimal
    oi_change: Decimal
    oi_change_pct: Decimal
    price: Decimal
    price_change: Decimal
    interpretation: str


@dataclass(frozen=True)
class IndexBreadth:
    advances: int
    declines: int
    unchanged: int
    advance_decline_ratio: Decimal
    bias: MarketBias


def pcr(
    call_oi: Decimal,
    put_oi: Decimal,
    call_volume: Decimal = _ZERO,
    put_volume: Decimal = _ZERO,
    use_volume: bool = False,
) -> PCRResult:
    """Put-Call Ratio from OI or volume data.

    PCR = Put OI / Call OI (or Put Vol / Call Vol)
    PCR > 1.2: Bullish (excessive put writing = support)
    PCR < 0.7: Bearish (excessive call writing = resistance)
    0.7-1.2: Neutral range
    """
    denom = call_volume if use_volume else call_oi
    if denom == _ZERO:
        return PCRResult(
            pcr=_ZERO,
            bias=MarketBias.NEUTRAL,
            call_oi=call_oi,
            put_oi=put_oi,
        )
    ratio = put_oi / denom if not use_volume else put_volume / denom
    if ratio >= Decimal("1.2"):
        bias = MarketBias.BULLISH
    elif ratio <= Decimal("0.7"):
        bias = MarketBias.BEARISH
    else:
        bias = MarketBias.NEUTRAL
    return PCRResult(
        pcr=ratio,
        bias=bias,
        call_oi=call_oi,
        put_oi=put_oi,
    )


def interpret_vix(vix_value: Decimal) -> VIXInterpretation:
    """Interpret India VIX value into market regime.

    VIX < 12: Complacency/Low vol — Bullish but watch for spike
    VIX 12-18: Normal range — Neutral
    VIX 18-25: Elevated fear — Mildly Bearish
    VIX > 25: High fear — Contrarian Bullish (mean reversion)
    """
    if vix_value < Decimal("12"):
        return VIXInterpretation(
            vix_value=vix_value,
            regime="LOW_VOLATILITY",
            bias=MarketBias.BULLISH,
            description="Low volatility — possible complacency",
        )
    if vix_value < Decimal("18"):
        return VIXInterpretation(
            vix_value=vix_value,
            regime="NORMAL",
            bias=MarketBias.NEUTRAL,
            description="Normal volatility regime",
        )
    if vix_value < Decimal("25"):
        return VIXInterpretation(
            vix_value=vix_value,
            regime="ELEVATED",
            bias=MarketBias.BEARISH,
            description="Elevated fear — mild bearishness",
        )
    return VIXInterpretation(
        vix_value=vix_value,
        regime="HIGH_FEAR",
        bias=MarketBias.BULLISH,
        description="Extreme fear — contrarian bullish signal",
    )


def analyze_oi(
    symbol: str,
    current_oi: Decimal,
    prev_oi: Decimal,
    price: Decimal,
    prev_price: Decimal,
) -> OIAnalysis:
    """Analyze OI change with price to determine market action.

    OI ↑ + Price ↑ = Long Buildup (Bullish)
    OI ↑ + Price ↓ = Short Buildup (Bearish)
    OI ↓ + Price ↑ = Short Covering (Bullish)
    OI ↓ + Price ↓ = Long Unwinding (Bearish)
    """
    oi_change = current_oi - prev_oi
    oi_change_pct = (oi_change / prev_oi * _HUNDRED) if prev_oi > _ZERO else _ZERO
    price_change = price - prev_price
    oi_up = oi_change > _ZERO
    price_up = price_change > _ZERO
    if oi_up and price_up:
        interp = "LONG_BUILDUP"
    elif oi_up and not price_up:
        interp = "SHORT_BUILDUP"
    elif not oi_up and price_up:
        interp = "SHORT_COVERING"
    else:
        interp = "LONG_UNWINDING"
    return OIAnalysis(
        symbol=symbol,
        current_oi=current_oi,
        prev_oi=prev_oi,
        oi_change=oi_change,
        oi_change_pct=oi_change_pct,
        price=price,
        price_change=price_change,
        interpretation=interp,
    )


def index_breadth(
    advances: int,
    declines: int,
    unchanged: int = 0,
) -> IndexBreadth:
    """Calculate Advance-Decline ratio and market breadth.

    A/D ratio > 1.5: Strong breadth (Bullish)
    A/D ratio 0.67-1.5: Mixed (Neutral)
    A/D ratio < 0.67: Weak breadth (Bearish)
    """
    if declines == 0:
        ad_ratio = Decimal(str(advances)) if advances > 0 else _ZERO
    else:
        ad_ratio = Decimal(str(advances)) / Decimal(str(declines))
    if ad_ratio >= Decimal("1.5"):
        bias = MarketBias.BULLISH
    elif ad_ratio <= Decimal("0.67"):
        bias = MarketBias.BEARISH
    else:
        bias = MarketBias.NEUTRAL
    return IndexBreadth(
        advances=advances,
        declines=declines,
        unchanged=unchanged,
        advance_decline_ratio=ad_ratio,
        bias=bias,
    )


def support_resistance_from_oi(
    strike_oi_data: dict[Decimal, Decimal],
    side: str = "call",
    top_n: int = 3,
) -> list[tuple[Decimal, Decimal]]:
    """Find key support/resistance levels from OI concentration.

    For calls: highest OI strikes = resistance
    For puts: highest OI strikes = support
    Returns top_n (strike, oi) pairs sorted by OI descending.
    """
    if not strike_oi_data:
        return []
    sorted_items = sorted(
        strike_oi_data.items(),
        key=lambda x: x[1],
        reverse=True,
    )
    return sorted_items[:top_n]
