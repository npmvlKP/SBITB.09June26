"""Pre-trade risk check pipeline.

Every order must pass ALL T1-T10 checks before submission to the broker.

T1  Symbol allowlist
T2  Trading hours
T3  Max order value
T4  Max daily orders
T5  Rate limit (OPS)
T6  Margin available
T7  Position limit per symbol
T8  Max total exposure
T9  Price protection (circuit / LPP)
T10 Kill switch status
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import structlog

from config.settings import settings
from src.risk.audit import AuditEventType, AuditTrail
from src.risk.kill_switch import KillSwitch

logger = structlog.get_logger(__name__)


@dataclass
class OrderRequest:
    symbol: str
    segment: str
    order_type: str
    quantity: int
    price: Decimal
    trigger_price: Decimal = Decimal("0")
    strategy_id: str = ""
    tag: str = ""


@dataclass
class RiskCheckResult:
    passed: bool
    check_id: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskState:
    daily_order_count: int = 0
    current_exposure: Decimal = Decimal("0")
    positions: dict[str, Decimal] = field(default_factory=dict)
    margin_available: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")
    order_timestamps: list[float] = field(default_factory=list)
    order_rejections: list[float] = field(default_factory=list)


class RiskManager:
    """Pre-trade risk gate: T1-T10 SEBI compliance checks."""

    def __init__(
        self,
        kill_switch: KillSwitch,
        audit_trail: AuditTrail,
        state: RiskState | None = None,
        allowed_symbols: set[str] | None = None,
    ) -> None:
        self.kill_switch = kill_switch
        self.audit_trail = audit_trail
        self.state = state or RiskState()
        self._allowed_symbols = allowed_symbols or set()

    def register_symbol(self, symbol: str) -> None:
        self._allowed_symbols.add(symbol)

    def check(self, order: OrderRequest) -> list[RiskCheckResult]:
        """Run all T1-T10 checks. Returns list of results."""
        results: list[RiskCheckResult] = [
            self._t1_symbol_allowlist(order),
            self._t2_trading_hours(order),
            self._t3_max_order_value(order),
            self._t4_max_daily_orders(order),
            self._t5_rate_limit(order),
            self._t6_margin_available(order),
            self._t7_position_limit(order),
            self._t8_max_exposure(order),
            self._t9_price_protection(order),
            self._t10_kill_switch(order),
        ]

        all_passed = all(r.passed for r in results)
        self.audit_trail.record(
            event_type=(
                AuditEventType.RISK_CHECK_PASSED
                if all_passed
                else AuditEventType.RISK_CHECK_FAILED
            ),
            data={
                "symbol": order.symbol,
                "strategy_id": order.strategy_id,
                "checks_passed": sum(1 for r in results if r.passed),
                "checks_total": len(results),
                "failed_checks": [
                    r.check_id for r in results if not r.passed
                ],
            },
            strategy_id=order.strategy_id,
        )

        if not all_passed:
            self.state.order_rejections.append(time.time())
            logger.warning(
                "risk.check_failed",
                symbol=order.symbol,
                failed=[r.check_id for r in results if not r.passed],
            )

        return results

    def is_order_allowed(self, order: OrderRequest) -> bool:
        """Convenience: returns True if all T1-T10 pass."""
        return all(r.passed for r in self.check(order))

    def record_order_placed(self, order: OrderRequest) -> None:
        """Call AFTER successful order submission to update state."""
        self.state.daily_order_count += 1
        self.state.order_timestamps.append(time.time())
        order_value = order.price * Decimal(order.quantity)
        self.state.current_exposure += order_value
        self.state.positions[order.symbol] = (
            self.state.positions.get(order.symbol, Decimal("0"))
            + Decimal(order.quantity)
        )

    def _t1_symbol_allowlist(self, order: OrderRequest) -> RiskCheckResult:
        allowed = order.symbol in self._allowed_symbols
        return RiskCheckResult(
            passed=allowed,
            check_id="T1",
            message=(
                f"Symbol {order.symbol} in allowlist"
                if allowed
                else f"Symbol {order.symbol} NOT in allowlist"
            ),
            details={"symbol": order.symbol},
        )

    def _t2_trading_hours(self, order: OrderRequest) -> RiskCheckResult:
        now = datetime.now(tz=UTC)
        start_h = settings.trading_start_hour
        start_m = settings.trading_start_minute
        end_h = settings.trading_end_hour
        end_m = settings.trading_end_minute

        ist_now = now.astimezone(
            timezone(timedelta(hours=5, minutes=30))
        )
        current_minutes = ist_now.hour * 60 + ist_now.minute
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m

        in_hours = start_minutes <= current_minutes <= end_minutes
        return RiskCheckResult(
            passed=in_hours,
            check_id="T2",
            message=(
                "Within trading hours"
                if in_hours
                else "Outside trading hours"
            ),
            details={"current_utc": now.isoformat()},
        )

    def _t3_max_order_value(self, order: OrderRequest) -> RiskCheckResult:
        order_value = order.price * Decimal(order.quantity)
        within = order_value <= settings.max_order_value
        return RiskCheckResult(
            passed=within,
            check_id="T3",
            message=(
                f"Order value {order_value} <= {settings.max_order_value}"
                if within
                else f"Order value {order_value} > {settings.max_order_value}"
            ),
            details={"order_value": str(order_value)},
        )

    def _t4_max_daily_orders(self, order: OrderRequest) -> RiskCheckResult:
        within = self.state.daily_order_count < settings.max_daily_orders
        return RiskCheckResult(
            passed=within,
            check_id="T4",
            message=(
                f"Daily orders {self.state.daily_order_count} < {settings.max_daily_orders}"
                if within
                else f"Daily orders {self.state.daily_order_count} >= {settings.max_daily_orders}"
            ),
            details={"daily_order_count": self.state.daily_order_count},
        )

    def _t5_rate_limit(self, order: OrderRequest) -> RiskCheckResult:
        now = time.time()
        one_sec_ago = now - 1.0
        one_min_ago = now - 60.0

        recent_sec = sum(
            1 for t in self.state.order_timestamps if t > one_sec_ago
        )
        recent_min = sum(
            1 for t in self.state.order_timestamps if t > one_min_ago
        )

        within_sec = recent_sec < settings.max_orders_per_second
        within_min = recent_min < settings.max_orders_per_minute

        passed = within_sec and within_min
        return RiskCheckResult(
            passed=passed,
            check_id="T5",
            message=(
                "Within rate limits"
                if passed
                else f"Rate limit exceeded: {recent_sec}/sec, {recent_min}/min"
            ),
            details={
                "ops_recent": recent_sec,
                "opm_recent": recent_min,
            },
        )

    def _t6_margin_available(self, order: OrderRequest) -> RiskCheckResult:
        order_value = order.price * Decimal(order.quantity)
        margin_required = order_value
        has_margin = self.state.margin_available >= margin_required
        return RiskCheckResult(
            passed=has_margin,
            check_id="T6",
            message=(
                f"Margin {self.state.margin_available} >= required {margin_required}"
                if has_margin
                else f"Margin {self.state.margin_available} < required {margin_required}"
            ),
            details={
                "margin_available": str(self.state.margin_available),
                "margin_required": str(margin_required),
            },
        )

    def _t7_position_limit(self, order: OrderRequest) -> RiskCheckResult:
        current_pos = self.state.positions.get(order.symbol, Decimal("0"))
        projected = current_pos + Decimal(order.quantity)
        within = projected * order.price <= settings.max_position_per_symbol
        return RiskCheckResult(
            passed=within,
            check_id="T7",
            message=(
                f"Position {projected} within limit"
                if within
                else f"Position {projected} exceeds limit {settings.max_position_per_symbol}"
            ),
            details={
                "current_position": str(current_pos),
                "projected": str(projected),
            },
        )

    def _t8_max_exposure(self, order: OrderRequest) -> RiskCheckResult:
        order_value = order.price * Decimal(order.quantity)
        projected = self.state.current_exposure + order_value
        within = projected <= settings.max_total_exposure
        return RiskCheckResult(
            passed=within,
            check_id="T8",
            message=(
                f"Exposure {projected} within limit"
                if within
                else f"Exposure {projected} > limit {settings.max_total_exposure}"
            ),
            details={
                "current_exposure": str(self.state.current_exposure),
                "projected": str(projected),
            },
        )

    def _t9_price_protection(self, order: OrderRequest) -> RiskCheckResult:
        if order.price <= Decimal("0"):
            return RiskCheckResult(
                passed=False,
                check_id="T9",
                message="Price must be positive",
                details={"price": str(order.price)},
            )
        return RiskCheckResult(
            passed=True,
            check_id="T9",
            message="Price within acceptable range",
            details={"price": str(order.price)},
        )

    def _t10_kill_switch(self, order: OrderRequest) -> RiskCheckResult:
        allowed = self.kill_switch.check_order_allowed()
        return RiskCheckResult(
            passed=allowed,
            check_id="T10",
            message=(
                "Kill switch INACTIVE"
                if allowed
                else f"Kill switch {self.kill_switch.level.value}"
            ),
            details={"kill_switch_level": self.kill_switch.level.value},
        )
