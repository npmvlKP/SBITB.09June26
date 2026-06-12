"""In-memory OHLCV cache with TTL for recent candles.

Stores the most recent candles per instrument to avoid
redundant REST calls during strategy evaluation.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, datetime, timedelta

import structlog

from src.data.providers import OHLCV

logger = structlog.get_logger(__name__)

_DEFAULT_TTL_SECONDS = 300
_DEFAULT_MAX_INSTRUMENTS = 500
_DEFAULT_MAX_CANDLES_PER_INSTRUMENT = 500


class OHLCVCache:
    """LRU cache for OHLCV candles with per-instrument TTL.

    Each instrument stores up to max_candles entries.
    Instruments expire after TTL seconds of inactivity.
    """

    def __init__(
        self,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        max_instruments: int = _DEFAULT_MAX_INSTRUMENTS,
        max_candles: int = _DEFAULT_MAX_CANDLES_PER_INSTRUMENT,
    ) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._max_instruments = max_instruments
        self._max_candles = max_candles
        self._data: OrderedDict[int, list[OHLCV]] = OrderedDict()
        self._last_access: dict[int, datetime] = {}

    def get(
        self,
        instrument_token: int,
        since: datetime | None = None,
    ) -> list[OHLCV]:
        """Retrieve cached candles, optionally filtered from 'since'."""
        self._evict_expired()
        if instrument_token not in self._data:
            return []
        self._last_access[instrument_token] = datetime.now(tz=UTC)
        self._data.move_to_end(instrument_token)
        candles = self._data[instrument_token]
        if since is not None:
            return [c for c in candles if c.timestamp >= since]
        return list(candles)

    def put(
        self,
        instrument_token: int,
        candles: list[OHLCV],
    ) -> None:
        """Store candles, merging with existing data by timestamp."""
        self._evict_expired()
        if instrument_token not in self._data:
            self._data[instrument_token] = []
        existing = self._data[instrument_token]
        existing_ts = {c.timestamp: i for i, c in enumerate(existing)}
        for candle in candles:
            if candle.timestamp in existing_ts:
                idx = existing_ts[candle.timestamp]
                existing[idx] = candle
            else:
                existing.append(candle)
                existing_ts[candle.timestamp] = len(existing) - 1
        existing.sort(key=lambda c: c.timestamp)
        if len(existing) > self._max_candles:
            self._data[instrument_token] = existing[-self._max_candles :]
        self._last_access[instrument_token] = datetime.now(tz=UTC)
        self._data.move_to_end(instrument_token)
        self._enforce_max_instruments()

    def latest(
        self,
        instrument_token: int,
    ) -> OHLCV | None:
        """Return the most recent candle for an instrument."""
        candles = self.get(instrument_token)
        if not candles:
            return None
        return candles[-1]

    def clear(self, instrument_token: int | None = None) -> None:
        """Clear cache for a specific instrument or all."""
        if instrument_token is not None:
            self._data.pop(instrument_token, None)
            self._last_access.pop(instrument_token, None)
        else:
            self._data.clear()
            self._last_access.clear()

    @property
    def size(self) -> int:
        """Number of instruments in cache."""
        return len(self._data)

    @property
    def total_candles(self) -> int:
        """Total candles across all instruments."""
        return sum(len(v) for v in self._data.values())

    def _evict_expired(self) -> None:
        """Remove instruments not accessed within TTL."""
        now = datetime.now(tz=UTC)
        expired = [
            token for token, last in self._last_access.items() if now - last > self._ttl
        ]
        for token in expired:
            self._data.pop(token, None)
            del self._last_access[token]

    def _enforce_max_instruments(self) -> None:
        """Evict oldest-accessed instruments when over limit."""
        while len(self._data) > self._max_instruments:
            oldest_key, _ = self._data.popitem(last=False)
            self._last_access.pop(oldest_key, None)
