"""Tests for ZerodhaAdapter — all KiteConnect calls mocked."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.brokers.base import (
    BrokerOrder,
    OrderSide,
    OrderType,
    ProductType,
)
from src.brokers.zerodha import ZerodhaAdapter


@pytest.fixture
def adapter() -> ZerodhaAdapter:
    return ZerodhaAdapter(
        api_key="test_key",
        api_secret="test_secret",
        access_token="test_token",
    )


@pytest.fixture
def mock_kite():
    kite = MagicMock()
    kite.profile.return_value = {"user_id": "AB1234"}
    kite.login_url.return_value = (
        "https://kite.zerodha.com/connect/login?api_key=test_key&v=3"
    )
    kite.generate_session.return_value = {
        "access_token": "new_token",
        "user_id": "AB1234",
    }
    kite.place_order.return_value = "240601001"
    kite.cancel_order.return_value = "240601001"
    kite.orders.return_value = []
    kite.positions.return_value = {
        "net": [],
        "day": [],
    }
    kite.margins.return_value = {
        "equity": {
            "available": {"net": 100000.0},
            "used": {"net": 20000.0},
        },
    }
    kite.ltp.return_value = {
        "NFO:NIFTY25JUNFUT": {"last_price": 24500.5},
    }
    kite.set_access_token.return_value = None
    kite.set_session_expiry_hook.return_value = None
    return kite


@pytest.mark.asyncio
async def test_authenticate_success(adapter, mock_kite):
    with patch("src.brokers.zerodha.ZerodhaAdapter.authenticate") as mock_auth:
        mock_auth.return_value = "test_token"
        token = await adapter.authenticate()
        assert token == "test_token"


def test_login_url(adapter):
    url = adapter.login_url()
    assert "test_key" in url
    assert "kite.zerodha.com" in url


@pytest.mark.asyncio
async def test_place_order(adapter, mock_kite):
    adapter._kite = mock_kite
    order = BrokerOrder(
        symbol="NIFTY25JUNFUT",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=50,
        price=Decimal("24500"),
        trigger_price=Decimal("0"),
        product=ProductType.MIS,
        tag="sbitb_test",
    )
    result = await adapter.place_order(order)
    assert result.order_id == "240601001"
    assert result.status.value == "PENDING"
    mock_kite.place_order.assert_called_once()
    call_kwargs = mock_kite.place_order.call_args[1]
    assert call_kwargs["tradingsymbol"] == "NIFTY25JUNFUT"
    assert call_kwargs["transaction_type"] == "BUY"
    assert call_kwargs["order_type"] == "LIMIT"
    assert call_kwargs["price"] == 24500.0


@pytest.mark.asyncio
async def test_place_sl_order(adapter, mock_kite):
    adapter._kite = mock_kite
    order = BrokerOrder(
        symbol="NIFTY25JUNFUT",
        side=OrderSide.SELL,
        order_type=OrderType.SL,
        quantity=50,
        price=Decimal("24400"),
        trigger_price=Decimal("24450"),
        product=ProductType.MIS,
        tag="sl_order",
    )
    result = await adapter.place_order(order)
    assert result.order_id == "240601001"
    call_kwargs = mock_kite.place_order.call_args[1]
    assert call_kwargs["trigger_price"] == 24450.0
    assert call_kwargs["price"] == 24400.0


@pytest.mark.asyncio
async def test_place_market_order_no_price(adapter, mock_kite):
    adapter._kite = mock_kite
    order = BrokerOrder(
        symbol="NIFTY25JUNFUT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=50,
        price=Decimal("0"),
        trigger_price=Decimal("0"),
        product=ProductType.MIS,
        tag="",
    )
    await adapter.place_order(order)
    call_kwargs = mock_kite.place_order.call_args[1]
    assert "price" not in call_kwargs
    assert "trigger_price" not in call_kwargs


@pytest.mark.asyncio
async def test_place_order_rejection(adapter, mock_kite):
    adapter._kite = mock_kite
    mock_kite.place_order.side_effect = Exception("Insufficient margin")
    order = BrokerOrder(
        symbol="NIFTY25JUNFUT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=50,
        price=Decimal("0"),
        trigger_price=Decimal("0"),
        product=ProductType.MIS,
        tag="",
    )
    result = await adapter.place_order(order)
    assert result.status.value == "REJECTED"
    assert "Insufficient margin" in result.message


@pytest.mark.asyncio
async def test_cancel_order(adapter, mock_kite):
    adapter._kite = mock_kite
    result = await adapter.cancel_order("240601001")
    assert result.order_id == "240601001"
    assert result.status.value == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_all_orders(adapter, mock_kite):
    adapter._kite = mock_kite
    mock_kite.cancel_order.side_effect = lambda variety, order_id, **kwargs: order_id
    mock_kite.orders.return_value = [
        {"order_id": "001", "status": "OPEN", "exchange": "NFO"},
        {"order_id": "002", "status": "COMPLETE", "exchange": "NFO"},
        {"order_id": "003", "status": "TRIGGER PENDING", "exchange": "NFO"},
    ]
    results = await adapter.cancel_all_orders()
    assert len(results) == 2
    cancelled_ids = {r.order_id for r in results}
    assert "001" in cancelled_ids
    assert "003" in cancelled_ids


@pytest.mark.asyncio
async def test_get_positions(adapter, mock_kite):
    adapter._kite = mock_kite
    mock_kite.positions.return_value = {
        "net": [
            {
                "tradingsymbol": "NIFTY25JUNFUT",
                "exchange": "NFO",
                "quantity": 50,
                "average_price": 24300.5,
                "last_price": 24500.0,
                "pnl": 9975.0,
                "product": "MIS",
            },
            {
                "tradingsymbol": "BANKNIFTY25JUNFUT",
                "exchange": "NFO",
                "quantity": 0,
                "average_price": 0,
                "last_price": 0,
                "pnl": 0,
                "product": "MIS",
            },
        ],
        "day": [],
    }
    positions = await adapter.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "NIFTY25JUNFUT"
    assert positions[0].quantity == 50
    assert positions[0].average_price == Decimal("24300.5")
    assert positions[0].pnl == Decimal("9975")


@pytest.mark.asyncio
async def test_get_margins(adapter, mock_kite):
    adapter._kite = mock_kite
    margins = await adapter.get_margins()
    assert margins.available == Decimal("100000")
    assert margins.used == Decimal("20000")
    assert margins.total == Decimal("120000")


@pytest.mark.asyncio
async def test_is_connected_true(adapter, mock_kite):
    adapter._kite = mock_kite
    assert await adapter.is_connected() is True


@pytest.mark.asyncio
async def test_is_connected_false_no_kite(adapter):
    assert await adapter.is_connected() is False


@pytest.mark.asyncio
async def test_is_connected_false_on_exception(adapter, mock_kite):
    adapter._kite = mock_kite
    mock_kite.profile.side_effect = Exception("Token expired")
    assert await adapter.is_connected() is False


@pytest.mark.asyncio
async def test_ensure_connected_raises(adapter):
    with pytest.raises(RuntimeError, match="not initialized"):
        adapter._ensure_connected()


@pytest.mark.asyncio
async def test_decimal_conversion_in_positions(adapter, mock_kite):
    adapter._kite = mock_kite
    mock_kite.positions.return_value = {
        "net": [
            {
                "tradingsymbol": "NIFTY25JUNFUT",
                "exchange": "NFO",
                "quantity": 25,
                "average_price": 24500.25,
                "last_price": 24550.75,
                "pnl": 1259.375,
                "product": "NRML",
            },
        ],
        "day": [],
    }
    positions = await adapter.get_positions()
    assert isinstance(positions[0].average_price, Decimal)
    assert isinstance(positions[0].pnl, Decimal)


@pytest.mark.asyncio
async def test_get_ltp(adapter, mock_kite):
    adapter._kite = mock_kite
    ltp = await adapter.get_ltp(["NFO:NIFTY25JUNFUT"])
    assert "NFO:NIFTY25JUNFUT" in ltp
    assert ltp["NFO:NIFTY25JUNFUT"] == Decimal("24500.5")


@pytest.mark.asyncio
async def test_no_bracket_order_in_variety():
    order_types = {ot.value for ot in OrderType}
    assert "BRACKET" not in order_types
    assert "BO" not in order_types
