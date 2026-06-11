"""Shared test fixtures for risk module tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.risk.audit import AuditTrail
from src.risk.kill_switch import KillSwitch
from src.risk.manager import OrderRequest, RiskManager, RiskState


@pytest.fixture
def kill_switch() -> KillSwitch:
    return KillSwitch()


@pytest.fixture
def audit_trail() -> AuditTrail:
    return AuditTrail()


@pytest.fixture
def risk_state() -> RiskState:
    return RiskState(
        daily_order_count=0,
        current_exposure=Decimal("0"),
        positions={},
        margin_available=Decimal("1000000"),
        margin_used=Decimal("0"),
    )


@pytest.fixture
def risk_manager(
    kill_switch: KillSwitch,
    audit_trail: AuditTrail,
    risk_state: RiskState,
) -> RiskManager:
    rm = RiskManager(
        kill_switch=kill_switch,
        audit_trail=audit_trail,
        state=risk_state,
        allowed_symbols={"NIFTY24620CE24000", "BANKNIFTY24620PE48000"},
    )
    return rm


@pytest.fixture
def valid_order() -> OrderRequest:
    return OrderRequest(
        symbol="NIFTY24620CE24000",
        segment="NFO",
        order_type="LIMIT",
        quantity=50,
        price=Decimal("150.00"),
        strategy_id="MOMENTUM:V1",
        tag="MOMENTUM:V1",
    )


@pytest.fixture
def bad_symbol_order() -> OrderRequest:
    return OrderRequest(
        symbol="UNKNOWN_SYMBOL",
        segment="NFO",
        order_type="LIMIT",
        quantity=50,
        price=Decimal("150.00"),
        strategy_id="MOMENTUM:V1",
    )
