"""Order execution engine — risk-gated pipeline.

Every order passes through:
  1. Kill switch guard (immediate fail if PAUSE/KILL)
  2. T1-T10 pre-trade risk checks via RiskManager
  3. Order submission to broker via BrokerInterface
  4. Audit trail recording at every stage
  5. Position state update on fill

No order is submitted to the broker unless ALL checks pass.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

from src.brokers.base import (
    BrokerInterface,
    BrokerOrder,
    BrokerOrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from src.risk.audit import AuditEventType, AuditTrail
from src.risk.kill_switch import KillSwitch, KillSwitchError
from src.risk.manager import OrderRequest, RiskManager

logger = structlog.get_logger(__name__)


class ExecutionStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    RISK_REJECTED = "RISK_REJECTED"
    KILL_SWITCH_BLOCKED = "KILL_SWITCH_BLOCKED"
    BROKER_SUBMITTED = "BROKER_SUBMITTED"
    BROKER_REJECTED = "BROKER_REJECTED"
    BROKER_ERROR = "BROKER_ERROR"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class ExecutionResult:
    order_id: str
    status: ExecutionStatus
    risk_checks_passed: bool
    failed_checks: list[str]
    broker_result: BrokerOrderResult | None
    submitted_at: datetime
    message: str
    data: dict[str, Any] = field(default_factory=dict)


class ExecutionEngine:
    """Risk-gated order execution pipeline.

    Usage:
        engine = ExecutionEngine(broker, risk_manager, kill_switch, audit)
        result = await engine.submit(order_request)

    The engine never bypasses risk checks or kill switch.
    """

    def __init__(
        self,
        broker: BrokerInterface,
        risk_manager: RiskManager,
        kill_switch: KillSwitch,
        audit_trail: AuditTrail,
        max_retries: int = 0,
        retry_delay_seconds: float = 0.5,
    ) -> None:
        self._broker = broker
        self._risk_manager = risk_manager
        self._kill_switch = kill_switch
        self._audit_trail = audit_trail
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds

    async def submit(self, order: OrderRequest) -> ExecutionResult:
        """Submit an order through the full risk-gated pipeline."""
        now = datetime.now(tz=UTC)

        kill_result = self._check_kill_switch(order, now)
        if kill_result is not None:
            return kill_result

        risk_result = self._check_risk(order, now)
        if risk_result is not None:
            return risk_result

        broker_order = self._to_broker_order(order)
        broker_result = await self._submit_with_retry(broker_order)

        if broker_result.status == OrderStatus.REJECTED:
            return self._handle_broker_rejection(order, broker_result, now)

        self._record_success(order, broker_result)

        return ExecutionResult(
            order_id=broker_result.order_id,
            status=ExecutionStatus.BROKER_SUBMITTED,
            risk_checks_passed=True,
            failed_checks=[],
            broker_result=broker_result,
            submitted_at=now,
            message="Order submitted to broker",
        )

    def _check_kill_switch(
        self, order: OrderRequest, now: datetime
    ) -> ExecutionResult | None:
        """Guard: reject immediately if kill switch is active."""
        try:
            self._kill_switch.guard()
        except KillSwitchError as exc:
            logger.critical(
                "execution.kill_switch_blocked",
                symbol=order.symbol,
                level=self._kill_switch.level.value,
            )
            self._audit_trail.record(
                event_type=AuditEventType.ORDER_REJECTED,
                data={
                    "symbol": order.symbol,
                    "reason": "KILL_SWITCH_ACTIVE",
                    "kill_switch_level": self._kill_switch.level.value,
                },
                strategy_id=order.strategy_id,
            )
            return ExecutionResult(
                order_id="",
                status=ExecutionStatus.KILL_SWITCH_BLOCKED,
                risk_checks_passed=False,
                failed_checks=["KILL_SWITCH"],
                broker_result=None,
                submitted_at=now,
                message=str(exc),
            )
        return None

    def _check_risk(self, order: OrderRequest, now: datetime) -> ExecutionResult | None:
        """Run T1-T10 risk checks; return rejection result if any fail."""
        results = self._risk_manager.check(order)
        failed_checks = [r.check_id for r in results if not r.passed]
        if failed_checks:
            logger.warning(
                "execution.risk_rejected",
                symbol=order.symbol,
                failed_checks=failed_checks,
            )
            return ExecutionResult(
                order_id="",
                status=ExecutionStatus.RISK_REJECTED,
                risk_checks_passed=False,
                failed_checks=failed_checks,
                broker_result=None,
                submitted_at=now,
                message=f"Failed risk checks: {', '.join(failed_checks)}",
            )
        return None

    def _handle_broker_rejection(
        self,
        order: OrderRequest,
        broker_result: BrokerOrderResult,
        now: datetime,
    ) -> ExecutionResult:
        """Record audit and return rejection result for broker-rejected order."""
        self._audit_trail.record(
            event_type=AuditEventType.ORDER_REJECTED,
            data={
                "symbol": order.symbol,
                "order_id": broker_result.order_id,
                "reason": broker_result.message,
            },
            strategy_id=order.strategy_id,
            order_id=broker_result.order_id,
        )
        return ExecutionResult(
            order_id=broker_result.order_id,
            status=ExecutionStatus.BROKER_REJECTED,
            risk_checks_passed=True,
            failed_checks=[],
            broker_result=broker_result,
            submitted_at=now,
            message=broker_result.message,
        )

    def _record_success(
        self,
        order: OrderRequest,
        broker_result: BrokerOrderResult,
    ) -> None:
        """Record order-placed/confirmed audit and update risk state."""
        self._risk_manager.record_order_placed(order)
        event_type = (
            AuditEventType.ORDER_PLACED
            if broker_result.status == OrderStatus.PENDING
            else AuditEventType.ORDER_CONFIRMED
        )
        self._audit_trail.record(
            event_type=event_type,
            data={
                "symbol": order.symbol,
                "order_id": broker_result.order_id,
                "side": order.order_type,
                "quantity": order.quantity,
                "price": str(order.price),
            },
            strategy_id=order.strategy_id,
            order_id=broker_result.order_id,
        )
        logger.info(
            "execution.order_submitted",
            order_id=broker_result.order_id,
            symbol=order.symbol,
            status=broker_result.status.value,
        )

    async def cancel(self, order_id: str, segment: str = "") -> ExecutionResult:
        """Cancel an existing order at the broker."""
        now = datetime.now(tz=UTC)
        try:
            broker_result = await self._broker.cancel_order(
                order_id=order_id, segment=segment
            )
        except Exception as exc:
            logger.error(
                "execution.cancel_error",
                order_id=order_id,
                error=str(exc),
            )
            return ExecutionResult(
                order_id=order_id,
                status=ExecutionStatus.BROKER_ERROR,
                risk_checks_passed=True,
                failed_checks=[],
                broker_result=None,
                submitted_at=now,
                message=f"Cancel failed: {exc}",
            )

        self._audit_trail.record(
            event_type=AuditEventType.ORDER_CANCELLED,
            data={"order_id": order_id, "message": broker_result.message},
            order_id=order_id,
        )

        return ExecutionResult(
            order_id=order_id,
            status=ExecutionStatus.CANCELLED,
            risk_checks_passed=True,
            failed_checks=[],
            broker_result=broker_result,
            submitted_at=now,
            message="Order cancelled",
        )

    async def _submit_with_retry(self, broker_order: BrokerOrder) -> BrokerOrderResult:
        """Submit order to broker with optional retry on transient errors."""
        last_exception: Exception | None = None
        for attempt in range(1 + self._max_retries):
            try:
                result = await self._broker.place_order(broker_order)
                return result
            except Exception as exc:
                last_exception = exc
                if attempt < self._max_retries:
                    logger.warning(
                        "execution.retry",
                        attempt=attempt + 1,
                        max_retries=self._max_retries,
                        error=str(exc),
                    )
                    await asyncio.sleep(self._retry_delay_seconds)
        raise last_exception  # type: ignore[misc]

    @staticmethod
    def _to_broker_order(order: OrderRequest) -> BrokerOrder:
        """Convert internal OrderRequest to BrokerOrder DTO."""
        side = OrderSide.BUY
        ot = OrderType.MARKET
        pt = ProductType.MIS

        for side_member in OrderSide:
            if side_member.value == order.order_type.upper() and side_member.value in (
                "BUY",
                "SELL",
            ):
                side = side_member
                break

        for ot_member in OrderType:
            if ot_member.value == order.order_type.upper():
                ot = ot_member
                break

        return BrokerOrder(
            symbol=order.symbol,
            side=side,
            order_type=ot,
            quantity=order.quantity,
            price=order.price,
            trigger_price=order.trigger_price,
            product=pt,
            tag=order.tag,
        )
