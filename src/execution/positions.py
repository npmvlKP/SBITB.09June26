"""Position tracker — real-time P&L, margin utilization, daily loss limit.

Tracks open positions, marks-to-market, and enforces:
  - Daily loss limit (triggers kill switch if breached)
  - Margin utilization threshold (warns / throttles)
  - Per-symbol position sizing
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import structlog

from config.settings import settings
from src.brokers.base import BrokerInterface, MarginInfo
from src.risk.audit import AuditEventType, AuditTrail
from src.risk.kill_switch import KillSwitch, KillSwitchLevel, KillSwitchPath
from src.risk.manager import RiskState

logger = structlog.get_logger(__name__)

IST_OFFSET = timezone(timedelta(hours=5, minutes=30))


@dataclass
class PositionSnapshot:
    symbol: str
    segment: str
    quantity: int
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    product: str
    timestamp: datetime


@dataclass
class DailyPnL:
    realized: Decimal = Decimal("0")
    unrealized: Decimal = Decimal("0")
    trading_date: str = ""

    @property
    def total(self) -> Decimal:
        return self.realized + self.unrealized


class PositionTracker:
    """Track positions, P&L, and enforce daily loss limits.

    Syncs with broker for real-time position and margin data.
    Triggers kill switch if daily loss limit is breached.
    """

    def __init__(
        self,
        broker: BrokerInterface,
        kill_switch: KillSwitch,
        audit_trail: AuditTrail,
        risk_state: RiskState,
        daily_loss_limit: Decimal | None = None,
        margin_threshold: Decimal | None = None,
    ) -> None:
        self._broker = broker
        self._kill_switch = kill_switch
        self._audit_trail = audit_trail
        self._risk_state = risk_state
        self._daily_loss_limit = (
            daily_loss_limit or settings.daily_loss_limit
        )
        self._margin_threshold = (
            margin_threshold or settings.margin_utilization_threshold
        )
        self._positions: dict[str, PositionSnapshot] = {}
        self._daily_pnl = DailyPnL()
        self._last_sync: datetime | None = None

    async def sync(self) -> None:
        """Fetch latest positions and margins from broker."""
        positions = await self._broker.get_positions()
        margins = await self._broker.get_margins()
        now = datetime.now(tz=UTC)

        self._positions.clear()
        total_unrealized = Decimal("0")

        for pos in positions:
            snapshot = PositionSnapshot(
                symbol=pos.symbol,
                segment=pos.segment,
                quantity=pos.quantity,
                entry_price=pos.average_price,
                current_price=pos.current_price,
                unrealized_pnl=pos.pnl,
                product=pos.product.value,
                timestamp=now,
            )
            self._positions[pos.symbol] = snapshot
            total_unrealized += pos.pnl

        self._daily_pnl.unrealized = total_unrealized
        self._risk_state.margin_available = margins.available
        self._risk_state.margin_used = margins.used
        self._risk_state.current_exposure = margins.total
        self._last_sync = now

        logger.info(
            "positions.synced",
            position_count=len(self._positions),
            unrealized_pnl=str(total_unrealized),
            margin_available=str(margins.available),
        )

        await self._check_daily_loss()
        await self._check_margin_utilization(margins)

    def update_fill(
        self,
        symbol: str,
        quantity: int,
        fill_price: Decimal,
        side: str,
    ) -> None:
        """Update position state after an order fill."""
        existing = self._positions.get(symbol)
        if existing is None:
            self._positions[symbol] = PositionSnapshot(
                symbol=symbol,
                segment="NFO",
                quantity=quantity if side == "BUY" else -quantity,
                entry_price=fill_price,
                current_price=fill_price,
                unrealized_pnl=Decimal("0"),
                product="MIS",
                timestamp=datetime.now(tz=UTC),
            )
        else:
            if side == "BUY":
                new_qty = existing.quantity + quantity
                if new_qty != 0:
                    total_cost = existing.entry_price * abs(
                        existing.quantity
                    ) + fill_price * quantity
                    existing.entry_price = total_cost / abs(new_qty)
                existing.quantity = new_qty
            else:
                realized = (fill_price - existing.entry_price) * Decimal(
                    abs(quantity)
                )
                self._daily_pnl.realized += realized
                existing.quantity -= quantity

            existing.current_price = fill_price
            existing.timestamp = datetime.now(tz=UTC)

        self._risk_state.positions[symbol] = Decimal(
            self._positions[symbol].quantity
        )
        logger.info(
            "positions.fill_updated",
            symbol=symbol,
            quantity=quantity,
            fill_price=str(fill_price),
            side=side,
        )

    def get_snapshot(self, symbol: str) -> PositionSnapshot | None:
        return self._positions.get(symbol)

    def get_all_snapshots(self) -> list[PositionSnapshot]:
        return list(self._positions.values())

    @property
    def daily_pnl(self) -> DailyPnL:
        return self._daily_pnl

    @property
    def last_sync(self) -> datetime | None:
        return self._last_sync

    async def _check_daily_loss(self) -> None:
        """Trigger kill switch if daily loss limit is breached."""
        total_pnl = self._daily_pnl.total
        if total_pnl < -self._daily_loss_limit:
            logger.critical(
                "positions.daily_loss_limit_breached",
                total_pnl=str(total_pnl),
                loss_limit=str(self._daily_loss_limit),
            )
            self._kill_switch.activate(
                level=KillSwitchLevel.KILL,
                path=KillSwitchPath.CLI,
                reason=f"Daily loss limit breached: P&L={total_pnl}, limit={self._daily_loss_limit}",
                order_count=self._risk_state.daily_order_count,
            )
            self._audit_trail.record(
                event_type=AuditEventType.KILL_SWITCH_ACTIVATED,
                data={
                    "reason": "DAILY_LOSS_LIMIT",
                    "pnl": str(total_pnl),
                    "limit": str(self._daily_loss_limit),
                },
            )

    async def _check_margin_utilization(self, margins: MarginInfo) -> None:
        """Warn or throttle if margin utilization exceeds threshold."""
        if margins.total == Decimal("0"):
            return
        utilization = margins.used / margins.total
        if utilization > self._margin_threshold:
            if utilization > Decimal("0.95"):
                logger.critical(
                    "positions.margin_critical",
                    utilization=str(utilization),
                    threshold=str(self._margin_threshold),
                )
                self._kill_switch.activate(
                    level=KillSwitchLevel.PAUSE,
                    path=KillSwitchPath.CLI,
                    reason=f"Margin utilization critical: {utilization:.2%}",
                    order_count=self._risk_state.daily_order_count,
                )
            else:
                logger.warning(
                    "positions.margin_warning",
                    utilization=str(utilization),
                    threshold=str(self._margin_threshold),
                )
                if self._kill_switch.level == KillSwitchLevel.INACTIVE:
                    self._kill_switch.activate(
                        level=KillSwitchLevel.THROTTLE,
                        path=KillSwitchPath.CLI,
                        reason=f"Margin utilization high: {utilization:.2%}",
                        order_count=self._risk_state.daily_order_count,
                    )
