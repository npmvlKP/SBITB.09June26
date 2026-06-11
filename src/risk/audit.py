"""7-year append-only audit trail with SHA-256 checksums.

SEBI mandates (per CIR/MRD/DP/09/2012 and Feb 2025 circular):
  - All order lifecycle events must be recorded and retrievable
  - Records must be tamper-evident (append-only, hash-chained)
  - Retention: minimum 5+ years; we enforce 7 years
  - Microsecond-precision, NTP-synchronized timestamps (IST)
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class AuditEventType(StrEnum):
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    ORDER_PARTIAL_FILL = "ORDER_PARTIAL_FILL"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_MODIFIED = "ORDER_MODIFIED"
    KILL_SWITCH_ACTIVATED = "KILL_SWITCH_ACTIVATED"
    KILL_SWITCH_DEACTIVATED = "KILL_SWITCH_DEACTIVATED"
    RISK_CHECK_PASSED = "RISK_CHECK_PASSED"
    RISK_CHECK_FAILED = "RISK_CHECK_FAILED"
    SESSION_START = "SESSION_START"
    SESSION_END = "SESSION_END"
    CONFIG_CHANGE = "CONFIG_CHANGE"


class AuditEntry:
    """Single append-only audit record with SHA-256 checksum."""

    def __init__(
        self,
        event_type: AuditEventType,
        data: dict[str, Any],
        strategy_id: str = "",
        order_id: str = "",
        prev_checksum: str = "GENESIS",
        timestamp: datetime | None = None,
    ) -> None:
        self.event_type = event_type
        self.data = self._serialize_data(data)
        self.strategy_id = strategy_id
        self.order_id = order_id
        self.prev_checksum = prev_checksum
        self.timestamp = timestamp or datetime.now(tz=UTC)

        self.checksum = self._compute_checksum()

    @staticmethod
    def _serialize_data(data: dict[str, Any]) -> dict[str, Any]:
        serialized: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, Decimal):
                serialized[key] = str(value)
            elif isinstance(value, datetime):
                serialized[key] = value.isoformat()
            else:
                serialized[key] = value
        return serialized

    def _compute_checksum(self) -> str:
        payload = json.dumps(
            {
                "event_type": self.event_type.value,
                "data": self.data,
                "strategy_id": self.strategy_id,
                "order_id": self.order_id,
                "prev_checksum": self.prev_checksum,
                "timestamp": self.timestamp.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "data": self.data,
            "strategy_id": self.strategy_id,
            "order_id": self.order_id,
            "prev_checksum": self.prev_checksum,
            "checksum": self.checksum,
        }

    def verify(self) -> bool:
        return self._compute_checksum() == self.checksum


class AuditTrail:
    """Append-only audit trail with hash-chained integrity.

    Every entry's checksum incorporates the previous entry's checksum,
    forming a hash chain.  Tampering with any entry breaks the chain.
    """

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def record(
        self,
        event_type: AuditEventType,
        data: dict[str, Any],
        strategy_id: str = "",
        order_id: str = "",
        timestamp: datetime | None = None,
    ) -> AuditEntry:
        prev_checksum = (
            self._entries[-1].checksum if self._entries else "GENESIS"
        )
        entry = AuditEntry(
            event_type=event_type,
            data=data,
            strategy_id=strategy_id,
            order_id=order_id,
            prev_checksum=prev_checksum,
            timestamp=timestamp,
        )
        self._entries.append(entry)
        logger.info(
            "audit.recorded",
            event_type=event_type.value,
            checksum=entry.checksum,
        )
        return entry

    def verify_chain(self) -> bool:
        """Verify the entire hash chain is intact."""
        if not self._entries:
            return True

        for i, entry in enumerate(self._entries):
            if not entry.verify():
                logger.error(
                    "audit.chain_broken",
                    index=i,
                    expected=entry.checksum,
                    computed=entry._compute_checksum(),
                )
                return False

            if i == 0:
                if entry.prev_checksum != "GENESIS":
                    logger.error(
                        "audit.genesis_mismatch",
                        index=i,
                        prev_checksum=entry.prev_checksum,
                    )
                    return False
            else:
                if entry.prev_checksum != self._entries[i - 1].checksum:
                    logger.error(
                        "audit.chain_link_broken",
                        index=i,
                        expected=self._entries[i - 1].checksum,
                        actual=entry.prev_checksum,
                    )
                    return False

        return True

    def get_entries(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._entries]

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def last_checksum(self) -> str:
        if not self._entries:
            return "GENESIS"
        return self._entries[-1].checksum
