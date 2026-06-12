"""Black-Scholes option Greeks for Indian F&O markets.

All calculations use Decimal for financial precision.
European-style options (valid for index options on NSE).
Uses NSE settlement calendar (252 trading days/year).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from math import erf, exp, log, sqrt

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")
_HUNDRED = Decimal("100")
_TRADING_DAYS_YEAR = 252
_SECONDS_PER_DAY = 86400


def _d1(
    spot: Decimal,
    strike: Decimal,
    time_to_expiry_years: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
) -> float:
    """Calculate d1 in Black-Scholes formula."""
    if (
        spot <= _ZERO
        or strike <= _ZERO
        or time_to_expiry_years <= _ZERO
        or volatility <= _ZERO
    ):
        return 0.0
    s = float(spot)
    k = float(strike)
    t = float(time_to_expiry_years)
    r = float(risk_free_rate)
    v = float(volatility)
    sqrt_t = sqrt(t)
    return (log(s / k) + (r + v * v / 2) * t) / (v * sqrt_t)


def _d2(
    d1_val: float,
    volatility: Decimal,
    time_to_expiry_years: Decimal,
) -> float:
    """Calculate d2 from d1."""
    return d1_val - float(volatility) * sqrt(float(time_to_expiry_years))


def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function approximation."""
    return (1 + erf(x / sqrt(2))) / 2


def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return exp(-x * x / 2) / sqrt(2 * 3.14159265358979323846)


def delta(
    spot: Decimal,
    strike: Decimal,
    time_to_expiry_years: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
    is_call: bool = True,
) -> Decimal:
    """Option delta.

    Call delta: N(d1), range [0, 1]
    Put delta: N(d1) - 1, range [-1, 0]
    """
    d1_val = _d1(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        volatility,
    )
    cdf = _norm_cdf(d1_val)
    if is_call:
        return Decimal(str(cdf))
    return Decimal(str(cdf - 1))


def gamma(
    spot: Decimal,
    strike: Decimal,
    time_to_expiry_years: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
) -> Decimal:
    """Option gamma — rate of change of delta per unit spot move.

    gamma = N'(d1) / (S * sigma * sqrt(T))
    """
    d1_val = _d1(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        volatility,
    )
    if spot <= _ZERO or volatility <= _ZERO or time_to_expiry_years <= _ZERO:
        return _ZERO
    pdf = _norm_pdf(d1_val)
    denom = float(spot) * float(volatility) * sqrt(float(time_to_expiry_years))
    if denom == 0:
        return _ZERO
    return Decimal(str(pdf / denom))


def theta(
    spot: Decimal,
    strike: Decimal,
    time_to_expiry_years: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
    is_call: bool = True,
) -> Decimal:
    """Option theta (daily, in rupees per lot).

    Returns theta per calendar day (annual theta / 365).
    Negative for long options (time decay).
    """
    d1_val = _d1(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        volatility,
    )
    d2_val = _d2(d1_val, volatility, time_to_expiry_years)
    if time_to_expiry_years <= _ZERO or volatility <= _ZERO:
        return _ZERO
    s = float(spot)
    k = float(strike)
    t = float(time_to_expiry_years)
    r = float(risk_free_rate)
    v = float(volatility)
    sqrt_t = sqrt(t)
    pdf_d1 = _norm_pdf(d1_val)
    term1 = -(s * pdf_d1 * v) / (2 * sqrt_t)
    if is_call:
        term2 = -r * k * exp(-r * t) * _norm_cdf(d2_val)
        annual = term1 + term2
    else:
        term2 = r * k * exp(-r * t) * _norm_cdf(-d2_val)
        annual = term1 + term2
    daily = annual / 365
    return Decimal(str(daily))


def vega(
    spot: Decimal,
    strike: Decimal,
    time_to_expiry_years: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
) -> Decimal:
    """Option vega — sensitivity to 1% change in IV.

    vega = S * N'(d1) * sqrt(T) / 100
    Returns per-1%-point change (divided by 100).
    """
    d1_val = _d1(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        volatility,
    )
    if time_to_expiry_years <= _ZERO:
        return _ZERO
    pdf = _norm_pdf(d1_val)
    val = float(spot) * pdf * sqrt(float(time_to_expiry_years)) / 100
    return Decimal(str(val))


def rho(
    spot: Decimal,
    strike: Decimal,
    time_to_expiry_years: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
    is_call: bool = True,
) -> Decimal:
    """Option rho — sensitivity to 1% change in risk-free rate.

    Call rho = K * T * e^(-rT) * N(d2) / 100
    Put rho = -K * T * e^(-rT) * N(-d2) / 100
    """
    d1_val = _d1(
        spot,
        strike,
        time_to_expiry_years,
        risk_free_rate,
        volatility,
    )
    d2_val = _d2(d1_val, volatility, time_to_expiry_years)
    k = float(strike)
    t = float(time_to_expiry_years)
    r = float(risk_free_rate)
    if is_call:
        val = k * t * exp(-r * t) * _norm_cdf(d2_val) / 100
    else:
        val = -k * t * exp(-r * t) * _norm_cdf(-d2_val) / 100
    return Decimal(str(val))


def time_to_expiry_years(
    expiry: datetime,
    now: datetime | None = None,
) -> Decimal:
    """Calculate time to expiry in years from current time.

    Uses calendar days (not trading days) per market convention.
    """
    if now is None:
        now = datetime.now(tz=UTC)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    diff_seconds = (expiry - now).total_seconds()
    if diff_seconds <= 0:
        return _ZERO
    days = diff_seconds / _SECONDS_PER_DAY
    return Decimal(str(days / 365.25))


def all_greeks(
    spot: Decimal,
    strike: Decimal,
    time_to_expiry_years: Decimal,
    risk_free_rate: Decimal,
    volatility: Decimal,
    is_call: bool = True,
) -> dict[str, Decimal]:
    """Calculate all Greeks at once. Returns {delta, gamma, theta, vega, rho}."""
    args = (spot, strike, time_to_expiry_years, risk_free_rate, volatility)
    return {
        "delta": delta(*args, is_call=is_call),
        "gamma": gamma(*args),
        "theta": theta(*args, is_call=is_call),
        "vega": vega(*args),
        "rho": rho(*args, is_call=is_call),
    }
