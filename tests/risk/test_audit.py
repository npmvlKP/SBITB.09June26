"""Tests for src/risk/audit.py — 7-year audit trail with SHA-256 checksums."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.risk.audit import AuditEntry, AuditEventType, AuditTrail


class TestAuditEntry:
    def test_entry_checksum_deterministic(self) -> None:
        data = {"order_value": Decimal("50000")}
        entry1 = AuditEntry(
            event_type=AuditEventType.ORDER_PLACED,
            data=data,
            strategy_id="STRAT1",
            prev_checksum="GENESIS",
            timestamp=datetime(2025, 6, 1, 9, 15, 0, tzinfo=timezone.utc),
        )
        entry2 = AuditEntry(
            event_type=AuditEventType.ORDER_PLACED,
            data=data,
            strategy_id="STRAT1",
            prev_checksum="GENESIS",
            timestamp=datetime(2025, 6, 1, 9, 15, 0, tzinfo=timezone.utc),
        )
        assert entry1.checksum == entry2.checksum

    def test_entry_verify_passes(self) -> None:
        entry = AuditEntry(
            event_type=AuditEventType.RISK_CHECK_PASSED,
            data={"symbol": "NIFTY"},
        )
        assert entry.verify() is True

    def test_decimal_serialization(self) -> None:
        entry = AuditEntry(
            event_type=AuditEventType.ORDER_PLACED,
            data={"price": Decimal("150.50")},
        )
        d = entry.to_dict()
        assert d["data"]["price"] == "150.50"


class TestAuditTrail:
    def test_hash_chain_integrity(self) -> None:
        trail = AuditTrail()
        trail.record(
            AuditEventType.SESSION_START, data={"user": "bot"}
        )
        trail.record(
            AuditEventType.ORDER_PLACED,
            data={"symbol": "NIFTY"},
            order_id="ORD001",
        )
        trail.record(
            AuditEventType.ORDER_FILLED,
            data={"fill_price": Decimal("150.00")},
            order_id="ORD001",
        )
        assert trail.verify_chain() is True
        assert trail.entry_count == 3

    def test_tampered_entry_breaks_chain(self) -> None:
        trail = AuditTrail()
        trail.record(AuditEventType.SESSION_START, data={"a": "1"})
        trail.record(AuditEventType.ORDER_PLACED, data={"b": "2"})
        trail._entries[1].data["b"] = "tampered"
        assert trail.verify_chain() is False

    def test_genesis_entry_prev_checksum(self) -> None:
        trail = AuditTrail()
        trail.record(AuditEventType.SESSION_START, data={})
        assert trail._entries[0].prev_checksum == "GENESIS"

    def test_chain_links_prev_checksum(self) -> None:
        trail = AuditTrail()
        e1 = trail.record(AuditEventType.SESSION_START, data={"i": 1})
        e2 = trail.record(AuditEventType.SESSION_END, data={"i": 2})
        assert e2.prev_checksum == e1.checksum
        assert trail.last_checksum == e2.checksum
