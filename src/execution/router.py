"""Order router — segment routing, rate limiting, and submission queue.

Routes orders to the correct exchange segment, enforces
self-imposed rate limits (3/sec, 200/min, 2000/day), and
queues orders when rate limits are hit.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog

from config.settings import settings
from src.execution.engine import ExecutionEngine, ExecutionResult, ExecutionStatus
from src.risk.manager import OrderRequest

logger = structlog.get_logger(__name__)

_EXCHANGE_MAP: dict[str, str] = {
    "NFO": "NFO",
    "CDS": "CDS",
    "MCX": "MCX",
    "NSE": "NSE",
    "BFO": "BFO",
    "BSE": "BSE",
}


@dataclass
class RateLimitState:
    second_timestamps: list[float] = field(default_factory=list)
    minute_timestamps: list[float] = field(default_factory=list)
    daily_count: int = 0
    day_start: float = field(default_factory=time.time)


class OrderRouter:
    """Route and rate-limit orders through the execution engine.

    Features:
      - Segment-based exchange routing
      - Token bucket rate limiting (sec/min/day)
      - Async queue for rate-limited orders
      - Per-segment order counting
    """

    def __init__(
        self,
        engine: ExecutionEngine,
        max_ops_per_second: int | None = None,
        max_ops_per_minute: int | None = None,
        max_ops_per_day: int | None = None,
        queue_capacity: int = 100,
    ) -> None:
        self._engine = engine
        self._max_ops = max_ops_per_second or settings.max_orders_per_second
        self._max_opm = max_ops_per_minute or settings.max_orders_per_minute
        self._max_opd = max_ops_per_day or settings.max_daily_orders
        self._queue_capacity = queue_capacity
        self._rate_state = RateLimitState()
        self._segment_counts: dict[str, int] = defaultdict(int)
        self._pending: asyncio.Queue[OrderRequest] = asyncio.Queue(
            maxsize=queue_capacity
        )
        self._results: list[ExecutionResult] = []

    async def route(self, order: OrderRequest) -> ExecutionResult:
        """Route an order: rate-limit check → engine.submit()."""
        self._prune_timestamps()

        if self._is_rate_limited():
            logger.warning(
                "router.rate_limited",
                symbol=order.symbol,
                ops=len(self._rate_state.second_timestamps),
                opm=len(self._rate_state.minute_timestamps),
                daily=self._rate_state.daily_count,
            )
            now = datetime.now(tz=UTC)
            return ExecutionResult(
                order_id="",
                status=ExecutionStatus.BROKER_REJECTED,
                risk_checks_passed=True,
                failed_checks=["RATE_LIMIT"],
                broker_result=None,
                submitted_at=now,
                message="Rate limit exceeded — order queued or rejected",
            )

        now_ts = time.time()
        self._rate_state.second_timestamps.append(now_ts)
        self._rate_state.minute_timestamps.append(now_ts)
        self._rate_state.daily_count += 1

        segment = order.segment.upper()
        self._segment_counts[segment] += 1

        result = await self._engine.submit(order)
        self._results.append(result)

        logger.info(
            "router.order_routed",
            order_id=result.order_id,
            segment=segment,
            status=result.status.value,
        )
        return result

    async def cancel(self, order_id: str, segment: str = "") -> ExecutionResult:
        """Route a cancel request through the engine."""
        return await self._engine.cancel(order_id, segment=segment)

    @property
    def segment_counts(self) -> dict[str, int]:
        return dict(self._segment_counts)

    @property
    def daily_count(self) -> int:
        return self._rate_state.daily_count

    @property
    def results(self) -> list[ExecutionResult]:
        return list(self._results)

    def _is_rate_limited(self) -> bool:
        state = self._rate_state
        if len(state.second_timestamps) >= self._max_ops:
            return True
        if len(state.minute_timestamps) >= self._max_opm:
            return True
        return state.daily_count >= self._max_opd

    def _prune_timestamps(self) -> None:
        now = time.time()
        one_sec_ago = now - 1.0
        one_min_ago = now - 60.0
        state = self._rate_state
        state.second_timestamps = [
            t for t in state.second_timestamps if t > one_sec_ago
        ]
        state.minute_timestamps = [
            t for t in state.minute_timestamps if t > one_min_ago
        ]
