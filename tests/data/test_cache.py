"""Tests for src/data/cache.py — OHLCV cache with TTL."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

from src.data.cache import OHLCVCache
from src.data.providers import OHLCV


def _candle(
    ts_minutes: int,
    close: str = "100",
    volume: int = 1000,
) -> OHLCV:
    return OHLCV(
        timestamp=datetime(2025, 6, 25, 9, ts_minutes, tzinfo=UTC),
        open=Decimal(close) - Decimal("5"),
        high=Decimal(close) + Decimal("5"),
        low=Decimal(close) - Decimal("10"),
        close=Decimal(close),
        volume=volume,
    )


class TestOHLCVCache:
    def test_put_and_get(self) -> None:
        cache = OHLCVCache(ttl_seconds=300)
        candles = [_candle(15), _candle(16), _candle(17)]
        cache.put(12345, candles)
        result = cache.get(12345)
        assert len(result) == 3
        assert result[0].close == Decimal("100")

    def test_get_missing_returns_empty(self) -> None:
        cache = OHLCVCache()
        result = cache.get(99999)
        assert result == []

    def test_get_with_since_filter(self) -> None:
        cache = OHLCVCache(ttl_seconds=300)
        candles = [_candle(15), _candle(16), _candle(17)]
        cache.put(12345, candles)
        since = datetime(2025, 6, 25, 9, 16, tzinfo=UTC)
        result = cache.get(12345, since=since)
        assert len(result) == 2

    def test_latest_returns_last(self) -> None:
        cache = OHLCVCache(ttl_seconds=300)
        candles = [_candle(15, "100"), _candle(16, "110")]
        cache.put(12345, candles)
        latest = cache.latest(12345)
        assert latest is not None
        assert latest.close == Decimal("110")

    def test_latest_missing_returns_none(self) -> None:
        cache = OHLCVCache()
        assert cache.latest(99999) is None

    def test_put_merges_by_timestamp(self) -> None:
        cache = OHLCVCache(ttl_seconds=300)
        cache.put(12345, [_candle(15, "100"), _candle(16, "110")])
        cache.put(12345, [_candle(16, "115"), _candle(17, "120")])
        result = cache.get(12345)
        assert len(result) == 3
        c16 = [c for c in result if c.timestamp.minute == 16][0]
        assert c16.close == Decimal("115")

    def test_put_sorts_by_timestamp(self) -> None:
        cache = OHLCVCache(ttl_seconds=300)
        cache.put(12345, [_candle(17, "120"), _candle(15, "100")])
        result = cache.get(12345)
        assert result[0].timestamp.minute == 15
        assert result[1].timestamp.minute == 17

    def test_max_candles_enforced(self) -> None:
        cache = OHLCVCache(ttl_seconds=300, max_candles=3)
        candles = [_candle(i, str(100 + i)) for i in range(15, 20)]
        cache.put(12345, candles)
        result = cache.get(12345)
        assert len(result) == 3

    def test_clear_specific_instrument(self) -> None:
        cache = OHLCVCache(ttl_seconds=300)
        cache.put(12345, [_candle(15)])
        cache.put(67890, [_candle(15)])
        cache.clear(12345)
        assert cache.get(12345) == []
        assert len(cache.get(67890)) == 1

    def test_clear_all(self) -> None:
        cache = OHLCVCache(ttl_seconds=300)
        cache.put(12345, [_candle(15)])
        cache.put(67890, [_candle(15)])
        cache.clear()
        assert cache.size == 0

    def test_size_and_total_candles(self) -> None:
        cache = OHLCVCache(ttl_seconds=300)
        cache.put(12345, [_candle(15), _candle(16)])
        cache.put(67890, [_candle(15)])
        assert cache.size == 2
        assert cache.total_candles == 3

    def test_evicts_expired(self) -> None:
        cache = OHLCVCache(ttl_seconds=1)
        cache.put(12345, [_candle(15)])
        time.sleep(2)
        assert cache.get(12345) == []
