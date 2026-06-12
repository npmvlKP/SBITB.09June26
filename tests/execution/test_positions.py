"""Tests for PositionTracker — P&L tracking, loss limits, margin alerts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.brokers.base import MarginInfo, Position, ProductType
from src.risk.kill_switch import KillSwitchLevel


@pytest.mark.asyncio
async def test_sync_fetches_positions(position_tracker, mock_broker):
    mock_broker.set_positions(
        [
            Position(
                symbol="NIFTY25JUNFUT",
                segment="NFO",
                quantity=50,
                average_price=Decimal("24300"),
                current_price=Decimal("24500"),
                pnl=Decimal("10000"),
                product=ProductType.MIS,
            ),
        ]
    )
    await position_tracker.sync()
    snapshot = position_tracker.get_snapshot("NIFTY25JUNFUT")
    assert snapshot is not None
    assert snapshot.quantity == 50
    assert snapshot.unrealized_pnl == Decimal("10000")


@pytest.mark.asyncio
async def test_sync_updates_margin(position_tracker, mock_broker, risk_state):
    mock_broker.set_margins(
        MarginInfo(
            available=Decimal("50000"),
            used=Decimal("30000"),
            total=Decimal("80000"),
        )
    )
    await position_tracker.sync()
    assert risk_state.margin_available == Decimal("50000")
    assert risk_state.margin_used == Decimal("30000")


@pytest.mark.asyncio
async def test_update_fill_buy_new(position_tracker, risk_state):
    position_tracker.update_fill(
        symbol="NIFTY25JUNFUT",
        quantity=50,
        fill_price=Decimal("24500"),
        side="BUY",
    )
    snapshot = position_tracker.get_snapshot("NIFTY25JUNFUT")
    assert snapshot is not None
    assert snapshot.quantity == 50
    assert risk_state.positions["NIFTY25JUNFUT"] == Decimal("50")


@pytest.mark.asyncio
async def test_update_fill_sell_realizes_pnl(position_tracker):
    position_tracker.update_fill(
        symbol="NIFTY25JUNFUT",
        quantity=50,
        fill_price=Decimal("24300"),
        side="BUY",
    )
    position_tracker.update_fill(
        symbol="NIFTY25JUNFUT",
        quantity=50,
        fill_price=Decimal("24500"),
        side="SELL",
    )
    assert position_tracker.daily_pnl.realized == Decimal("10000")


@pytest.mark.asyncio
async def test_daily_loss_limit_triggers_kill(
    position_tracker, mock_broker, kill_switch, risk_state
):
    mock_broker.set_positions(
        [
            Position(
                symbol="NIFTY25JUNFUT",
                segment="NFO",
                quantity=50,
                average_price=Decimal("25000"),
                current_price=Decimal("24000"),
                pnl=Decimal("-60000"),
                product=ProductType.MIS,
            ),
        ]
    )
    mock_broker.set_margins(
        MarginInfo(
            available=Decimal("100000"),
            used=Decimal("20000"),
            total=Decimal("120000"),
        )
    )
    await position_tracker.sync()
    assert kill_switch.level == KillSwitchLevel.KILL


@pytest.mark.asyncio
async def test_margin_warning_triggers_throttle(
    position_tracker, mock_broker, kill_switch, risk_state
):
    mock_broker.set_positions([])
    mock_broker.set_margins(
        MarginInfo(
            available=Decimal("10000"),
            used=Decimal("100000"),
            total=Decimal("110000"),
        )
    )
    await position_tracker.sync()
    assert kill_switch.level in (
        KillSwitchLevel.THROTTLE,
        KillSwitchLevel.PAUSE,
    )


@pytest.mark.asyncio
async def test_daily_pnl_total(position_tracker):
    position_tracker._daily_pnl.realized = Decimal("5000")
    position_tracker._daily_pnl.unrealized = Decimal("-3000")
    assert position_tracker.daily_pnl.total == Decimal("2000")


@pytest.mark.asyncio
async def test_get_all_snapshots(position_tracker, mock_broker):
    mock_broker.set_positions(
        [
            Position(
                symbol="NIFTY25JUNFUT",
                segment="NFO",
                quantity=50,
                average_price=Decimal("24300"),
                current_price=Decimal("24500"),
                pnl=Decimal("10000"),
                product=ProductType.MIS,
            ),
            Position(
                symbol="BANKNIFTY25JUNFUT",
                segment="NFO",
                quantity=25,
                average_price=Decimal("52000"),
                current_price=Decimal("52500"),
                pnl=Decimal("12500"),
                product=ProductType.MIS,
            ),
        ]
    )
    await position_tracker.sync()
    snapshots = position_tracker.get_all_snapshots()
    assert len(snapshots) == 2
