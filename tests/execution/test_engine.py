"""Tests for ExecutionEngine — risk-gated order pipeline."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.execution.engine import ExecutionStatus
from src.risk.kill_switch import KillSwitchLevel, KillSwitchPath
from src.risk.manager import OrderRequest


@pytest.mark.asyncio
async def test_submit_valid_order_passes_risk(
    execution_engine, mock_broker, valid_order
):
    result = await execution_engine.submit(valid_order)
    assert result.status == ExecutionStatus.BROKER_SUBMITTED
    assert result.risk_checks_passed is True
    assert result.failed_checks == []
    assert result.order_id != ""
    assert len(mock_broker.place_order_calls) == 1


@pytest.mark.asyncio
async def test_submit_records_audit_on_success(
    execution_engine, audit_trail, valid_order
):
    await execution_engine.submit(valid_order)
    assert audit_trail.entry_count >= 2


@pytest.mark.asyncio
async def test_submit_blocked_by_kill_switch(
    execution_engine, kill_switch, valid_order
):
    kill_switch.activate(
        KillSwitchLevel.KILL,
        path=KillSwitchPath.CLI,
        reason="test",
    )
    result = await execution_engine.submit(valid_order)
    assert result.status == ExecutionStatus.KILL_SWITCH_BLOCKED
    assert "KILL_SWITCH" in result.failed_checks
    assert result.risk_checks_passed is False


@pytest.mark.asyncio
async def test_submit_blocked_by_kill_switch_pause(
    execution_engine, kill_switch, valid_order
):
    kill_switch.activate(
        KillSwitchLevel.PAUSE,
        path=KillSwitchPath.CLI,
        reason="test pause",
    )
    result = await execution_engine.submit(valid_order)
    assert result.status == ExecutionStatus.KILL_SWITCH_BLOCKED


@pytest.mark.asyncio
async def test_submit_risk_rejected_bad_symbol(execution_engine):
    bad_order = OrderRequest(
        symbol="UNKNOWN_SYMBOL",
        segment="NFO",
        order_type="MARKET",
        quantity=50,
        price=Decimal("200"),
        strategy_id="test",
    )
    result = await execution_engine.submit(bad_order)
    assert result.status == ExecutionStatus.RISK_REJECTED
    assert "T1" in result.failed_checks
    assert result.risk_checks_passed is False


@pytest.mark.asyncio
async def test_submit_risk_rejected_insufficient_margin(execution_engine):
    expensive_order = OrderRequest(
        symbol="NIFTY25JUNFUT",
        segment="NFO",
        order_type="MARKET",
        quantity=5000,
        price=Decimal("200"),
        strategy_id="test",
    )
    result = await execution_engine.submit(expensive_order)
    assert result.status == ExecutionStatus.RISK_REJECTED
    assert "T6" in result.failed_checks


@pytest.mark.asyncio
async def test_submit_broker_rejected(
    execution_engine, mock_broker, valid_order
):
    mock_broker.set_should_reject(True)
    result = await execution_engine.submit(valid_order)
    assert result.status == ExecutionStatus.BROKER_REJECTED
    assert result.risk_checks_passed is True


@pytest.mark.asyncio
async def test_cancel_order(execution_engine, audit_trail):
    result = await execution_engine.cancel("12345")
    assert result.status == ExecutionStatus.CANCELLED
    assert result.order_id == "12345"


@pytest.mark.asyncio
async def test_kill_switch_guard_records_audit(
    execution_engine, audit_trail, kill_switch, valid_order
):
    kill_switch.activate(
        KillSwitchLevel.KILL,
        path=KillSwitchPath.CLI,
        reason="audit test",
    )
    await execution_engine.submit(valid_order)
    entries = audit_trail.get_entries()
    rejection_events = [
        e for e in entries if e["event_type"] == "ORDER_REJECTED"
    ]
    assert len(rejection_events) >= 1
    assert "KILL_SWITCH_ACTIVE" in rejection_events[0]["data"]["reason"]


@pytest.mark.asyncio
async def test_throttle_allows_orders(
    execution_engine, kill_switch, valid_order
):
    kill_switch.activate(
        KillSwitchLevel.THROTTLE,
        path=KillSwitchPath.CLI,
        reason="throttle test",
    )
    result = await execution_engine.submit(valid_order)
    assert result.status == ExecutionStatus.BROKER_SUBMITTED
