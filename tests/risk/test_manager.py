"""Tests for src/risk/manager.py — T1-T10 pre-trade risk checks."""

from __future__ import annotations

from decimal import Decimal

from config.settings import KillSwitchLevel
from src.risk.kill_switch import KillSwitchPath
from src.risk.manager import OrderRequest, RiskManager


class TestRiskManagerT1T10:
    def test_t1_symbol_not_in_allowlist(
        self,
        risk_manager: RiskManager,
        bad_symbol_order: OrderRequest,
    ) -> None:
        results = risk_manager.check(bad_symbol_order)
        t1 = next(r for r in results if r.check_id == "T1")
        assert t1.passed is False

    def test_t1_symbol_in_allowlist(
        self,
        risk_manager: RiskManager,
        valid_order: OrderRequest,
    ) -> None:
        results = risk_manager.check(valid_order)
        t1 = next(r for r in results if r.check_id == "T1")
        assert t1.passed is True

    def test_t3_exceeds_max_order_value(
        self, risk_manager: RiskManager
    ) -> None:
        huge_order = OrderRequest(
            symbol="NIFTY24620CE24000",
            segment="NFO",
            order_type="LIMIT",
            quantity=10000,
            price=Decimal("500.00"),
        )
        results = risk_manager.check(huge_order)
        t3 = next(r for r in results if r.check_id == "T3")
        assert t3.passed is False

    def test_t6_insufficient_margin(
        self, risk_manager: RiskManager
    ) -> None:
        risk_manager.state.margin_available = Decimal("100")
        order = OrderRequest(
            symbol="NIFTY24620CE24000",
            segment="NFO",
            order_type="LIMIT",
            quantity=50,
            price=Decimal("150.00"),
        )
        results = risk_manager.check(order)
        t6 = next(r for r in results if r.check_id == "T6")
        assert t6.passed is False

    def test_t10_kill_switch_blocks_order(
        self,
        risk_manager: RiskManager,
        valid_order: OrderRequest,
    ) -> None:
        risk_manager.kill_switch.activate(
            KillSwitchLevel.KILL,
            path=KillSwitchPath.CLI,
            reason="emergency",
        )
        results = risk_manager.check(valid_order)
        t10 = next(r for r in results if r.check_id == "T10")
        assert t10.passed is False

    def test_all_checks_pass_for_valid_order(
        self,
        risk_manager: RiskManager,
        valid_order: OrderRequest,
    ) -> None:
        results = risk_manager.check(valid_order)
        check_ids = [r.check_id for r in results]
        assert set(check_ids) == {
            "T1", "T2", "T3", "T4", "T5",
            "T6", "T7", "T8", "T9", "T10",
        }

    def test_is_order_allowed_returns_false_on_failure(
        self,
        risk_manager: RiskManager,
        bad_symbol_order: OrderRequest,
    ) -> None:
        assert risk_manager.is_order_allowed(bad_symbol_order) is False

    def test_audit_trail_records_risk_check(
        self,
        risk_manager: RiskManager,
        valid_order: OrderRequest,
    ) -> None:
        initial_count = risk_manager.audit_trail.entry_count
        risk_manager.check(valid_order)
        assert risk_manager.audit_trail.entry_count == initial_count + 1
