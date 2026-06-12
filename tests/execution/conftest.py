"""Shared fixtures for execution tests — mock broker, risk manager, etc."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from src.brokers.base import (
    BrokerInterface,
    BrokerOrder,
    BrokerOrderResult,
    MarginInfo,
    OrderStatus,
    Position,
)
from src.execution.engine import ExecutionEngine
from src.execution.positions import PositionTracker
from src.execution.router import OrderRouter
from src.risk.audit import AuditTrail
from src.risk.kill_switch import KillSwitch
from src.risk.manager import OrderRequest, RiskCheckResult, RiskManager, RiskState


class MockBroker(BrokerInterface):
    """In-memory mock broker for testing — no network calls."""

    def __init__(self) -> None:
        self._orders: dict[str, dict[str, Any]] = {}
        self._next_id = 1
        self._should_reject = False
        self._positions: list[Position] = []
        self._margins = MarginInfo(
            available=Decimal("100000"),
            used=Decimal("20000"),
            total=Decimal("120000"),
        )
        self._connected = True
        self._place_order_calls: list[BrokerOrder] = []

    async def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        self._place_order_calls.append(order)
        if self._should_reject:
            return BrokerOrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                message="Mock rejection",
            )
        oid = str(self._next_id)
        self._next_id += 1
        self._orders[oid] = {"order": order, "status": "OPEN"}
        return BrokerOrderResult(
            order_id=oid,
            status=OrderStatus.PENDING,
            message="Order placed",
            data={"mock": True},
        )

    async def cancel_order(self, order_id: str, segment: str = "") -> BrokerOrderResult:
        if order_id in self._orders:
            self._orders[order_id]["status"] = "CANCELLED"
        return BrokerOrderResult(
            order_id=order_id,
            status=OrderStatus.CANCELLED,
            message="Cancelled",
        )

    async def cancel_all_orders(self) -> list[BrokerOrderResult]:
        results = []
        for oid, data in self._orders.items():
            if data["status"] == "OPEN":
                data["status"] = "CANCELLED"
                results.append(
                    BrokerOrderResult(
                        order_id=oid,
                        status=OrderStatus.CANCELLED,
                        message="Cancelled",
                    )
                )
        return results

    async def get_orders(self) -> list[dict[str, Any]]:
        return [{"order_id": oid, **data} for oid, data in self._orders.items()]

    async def get_positions(self) -> list[Position]:
        return list(self._positions)

    async def get_margins(self) -> MarginInfo:
        return self._margins

    async def authenticate(self) -> str:
        self._connected = True
        return "mock_token"

    async def is_connected(self) -> bool:
        return self._connected

    def set_positions(self, positions: list[Position]) -> None:
        self._positions = positions

    def set_margins(self, margins: MarginInfo) -> None:
        self._margins = margins

    def set_should_reject(self, reject: bool) -> None:
        self._should_reject = reject

    @property
    def place_order_calls(self) -> list[BrokerOrder]:
        return self._place_order_calls


@pytest.fixture
def mock_broker() -> MockBroker:
    return MockBroker()


@pytest.fixture
def kill_switch() -> KillSwitch:
    return KillSwitch()


@pytest.fixture
def audit_trail() -> AuditTrail:
    return AuditTrail()


@pytest.fixture
def risk_state() -> RiskState:
    return RiskState(margin_available=Decimal("100000"))


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
        allowed_symbols={"NIFTY25JUNFUT", "BANKNIFTY25JUNFUT"},
    )
    rm._t2_trading_hours = lambda order: RiskCheckResult(
        passed=True,
        check_id="T2",
        message="Within trading hours (mocked)",
        details={"mocked": True},
    )
    return rm


@pytest.fixture
def execution_engine(
    mock_broker: MockBroker,
    risk_manager: RiskManager,
    kill_switch: KillSwitch,
    audit_trail: AuditTrail,
) -> ExecutionEngine:
    return ExecutionEngine(
        broker=mock_broker,
        risk_manager=risk_manager,
        kill_switch=kill_switch,
        audit_trail=audit_trail,
    )


@pytest.fixture
def order_router(execution_engine: ExecutionEngine) -> OrderRouter:
    return OrderRouter(
        engine=execution_engine,
        max_ops_per_second=3,
        max_ops_per_minute=200,
        max_ops_per_day=2000,
    )


@pytest.fixture
def position_tracker(
    mock_broker: MockBroker,
    kill_switch: KillSwitch,
    audit_trail: AuditTrail,
    risk_state: RiskState,
) -> PositionTracker:
    return PositionTracker(
        broker=mock_broker,
        kill_switch=kill_switch,
        audit_trail=audit_trail,
        risk_state=risk_state,
    )


@pytest.fixture
def valid_order() -> OrderRequest:
    return OrderRequest(
        symbol="NIFTY25JUNFUT",
        segment="NFO",
        order_type="MARKET",
        quantity=50,
        price=Decimal("200"),
        strategy_id="test_strat",
        tag="sbitb_test",
    )
