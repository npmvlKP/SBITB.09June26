"""Tests for OrderRouter — rate limiting and segment routing."""

from __future__ import annotations

import pytest

from src.execution.engine import ExecutionStatus


@pytest.mark.asyncio
async def test_route_valid_order(order_router, valid_order):
    result = await order_router.route(valid_order)
    assert result.status == ExecutionStatus.BROKER_SUBMITTED


@pytest.mark.asyncio
async def test_route_increments_daily_count(order_router, valid_order):
    assert order_router.daily_count == 0
    await order_router.route(valid_order)
    assert order_router.daily_count == 1


@pytest.mark.asyncio
async def test_route_tracks_segment(order_router, valid_order):
    await order_router.route(valid_order)
    assert order_router.segment_counts.get("NFO", 0) == 1


@pytest.mark.asyncio
async def test_route_rate_limited_per_second(order_router, valid_order):
    for _ in range(3):
        await order_router.route(valid_order)
    result = await order_router.route(valid_order)
    assert result.status == ExecutionStatus.BROKER_REJECTED
    assert "RATE_LIMIT" in result.failed_checks


@pytest.mark.asyncio
async def test_cancel_routes_through(order_router):
    result = await order_router.cancel("12345")
    assert result.status == ExecutionStatus.CANCELLED


@pytest.mark.asyncio
async def test_results_stored(order_router, valid_order):
    await order_router.route(valid_order)
    assert len(order_router.results) == 1
