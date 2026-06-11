"""Zerodha KiteConnect broker adapter.

Concrete implementation of BrokerInterface for Zerodha Kite.
Handles auth, order placement, position/margin queries, and
float↔Decimal conversion at the adapter boundary.

Key constraints:
  - NO sandbox environment exists — paper trading mode only
  - Bracket orders DISABLED since 2021
  - Daily access token expires at 06:00 IST
  - Rate limits: 10/sec, 400/min, 5000/day
  - WebSocket: 3000 subs/connection, max 3 connections
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import structlog

from src.brokers.base import (
    BrokerInterface,
    BrokerOrder,
    BrokerOrderResult,
    MarginInfo,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    ProductType,
)

logger = structlog.get_logger(__name__)

IST_OFFSET = timezone(timedelta(hours=5, minutes=30))

_VARIETY_REGULAR = "regular"
_VARIETY_AMO = "amo"

_EXCHANGE_NFO = "NFO"
_EXCHANGE_NSE = "NSE"
_EXCHANGE_CDS = "CDS"
_EXCHANGE_MCX = "MCX"

_PRODUCT_MAP: dict[ProductType, str] = {
    ProductType.MIS: "MIS",
    ProductType.NRML: "NRML",
    ProductType.CNC: "CNC",
}

_ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.SL: "SL",
    OrderType.SL_M: "SL-M",
}

_SIDE_MAP: dict[OrderSide, str] = {
    OrderSide.BUY: "BUY",
    OrderSide.SELL: "SELL",
}


class ZerodhaAdapter(BrokerInterface):
    """Zerodha KiteConnect adapter implementing BrokerInterface.

    All prices are converted from Decimal→float on the way out
    and float→Decimal on the way in, ensuring the core never
    touches float for financial values.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str = "",
        access_token: str = "",
        session_expiry_hook: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token
        self._session_expiry_hook = session_expiry_hook
        self._kite: Any = None

    async def authenticate(self) -> str:
        """Initialize KiteConnect session with existing access token."""
        try:
            from kiteconnect import KiteConnect  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "kiteconnect not installed. Run: pip install kiteconnect"
            ) from exc

        self._kite = KiteConnect(
            api_key=self._api_key,
            access_token=self._access_token,
        )

        if self._session_expiry_hook is not None:
            self._kite.set_session_expiry_hook(self._session_expiry_hook)

        try:
            self._kite.profile()
        except Exception as exc:
            logger.error("zerodha.auth_failed", error=str(exc))
            raise

        logger.info("zerodha.authenticated", api_key=self._api_key)
        return self._access_token

    async def generate_session(
        self, request_token: str
    ) -> dict[str, Any]:
        """Complete OAuth flow: exchange request_token for access_token."""
        try:
            from kiteconnect import KiteConnect  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "kiteconnect not installed. Run: pip install kiteconnect"
            ) from exc

        if self._kite is None:
            self._kite = KiteConnect(api_key=self._api_key)

        data = self._kite.generate_session(
            request_token=request_token,
            api_secret=self._api_secret,
        )
        self._access_token = data.get("access_token", "")
        self._kite.set_access_token(self._access_token)

        if self._session_expiry_hook is not None:
            self._kite.set_session_expiry_hook(self._session_expiry_hook)

        logger.info("zerodha.session_generated")
        return data

    def login_url(self) -> str:
        """Return Zerodha Kite login URL for OAuth redirect."""
        try:
            from kiteconnect import KiteConnect  # noqa: PLC0415

            kite = KiteConnect(api_key=self._api_key)
            return kite.login_url()
        except ImportError:
            return f"https://kite.zerodha.com/connect/login?api_key={self._api_key}&v=3"

    async def place_order(self, order: BrokerOrder) -> BrokerOrderResult:
        """Place order via KiteConnect. Converts Decimal→float for SDK."""
        self._ensure_connected()

        try:
            params: dict[str, Any] = {
                "variety": _VARIETY_REGULAR,
                "exchange": _EXCHANGE_NFO,
                "tradingsymbol": order.symbol,
                "transaction_type": _SIDE_MAP[order.side],
                "quantity": order.quantity,
                "product": _PRODUCT_MAP[order.product],
                "order_type": _ORDER_TYPE_MAP[order.order_type],
                "tag": order.tag if order.tag else None,
            }

            if order.order_type in (OrderType.LIMIT, OrderType.SL):
                params["price"] = float(order.price)

            if order.order_type in (OrderType.SL, OrderType.SL_M):
                params["trigger_price"] = float(order.trigger_price)

            order_id: str = self._kite.place_order(**params)

            logger.info(
                "zerodha.order_placed",
                order_id=order_id,
                symbol=order.symbol,
                side=order.side.value,
            )

            return BrokerOrderResult(
                order_id=order_id,
                status=OrderStatus.PENDING,
                message="Order placed successfully",
                data={"variety": _VARIETY_REGULAR},
            )

        except Exception as exc:
            logger.error(
                "zerodha.order_error",
                symbol=order.symbol,
                error=str(exc),
            )
            return BrokerOrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                message=str(exc),
            )

    async def cancel_order(
        self, order_id: str, segment: str = ""
    ) -> BrokerOrderResult:
        """Cancel an existing order."""
        self._ensure_connected()

        try:
            cancelled_id: str = self._kite.cancel_order(
                variety=_VARIETY_REGULAR,
                order_id=order_id,
            )
            logger.info("zerodha.order_cancelled", order_id=cancelled_id)
            return BrokerOrderResult(
                order_id=cancelled_id,
                status=OrderStatus.CANCELLED,
                message="Order cancelled",
            )
        except Exception as exc:
            logger.error(
                "zerodha.cancel_error",
                order_id=order_id,
                error=str(exc),
            )
            return BrokerOrderResult(
                order_id=order_id,
                status=OrderStatus.REJECTED,
                message=str(exc),
            )

    async def cancel_all_orders(self) -> list[BrokerOrderResult]:
        """Cancel all open orders."""
        self._ensure_connected()

        orders = self._kite.orders()
        results: list[BrokerOrderResult] = []

        for o in orders:
            if o.get("status") in ("OPEN", "PENDING", "TRIGGER PENDING"):
                result = await self.cancel_order(
                    order_id=o["order_id"],
                    segment=o.get("exchange", ""),
                )
                results.append(result)

        logger.info(
            "zerodha.cancel_all",
            cancelled_count=len(results),
        )
        return results

    async def get_orders(self) -> list[dict[str, Any]]:
        """Fetch all orders from Zerodha."""
        self._ensure_connected()
        return self._kite.orders()

    async def get_positions(self) -> list[Position]:
        """Fetch current positions, converting float→Decimal."""
        self._ensure_connected()
        data = self._kite.positions()
        positions: list[Position] = []

        for entry in data.get("net", []):
            if entry.get("quantity", 0) == 0:
                continue
            positions.append(
                Position(
                    symbol=entry.get("tradingsymbol", ""),
                    segment=entry.get("exchange", ""),
                    quantity=entry.get("quantity", 0),
                    average_price=Decimal(str(entry.get("average_price", 0))),
                    current_price=Decimal(str(entry.get("last_price", 0))),
                    pnl=Decimal(str(entry.get("pnl", 0))),
                    product=ProductType(
                        entry.get("product", "MIS").upper()
                    ),
                )
            )
        return positions

    async def get_margins(self) -> MarginInfo:
        """Fetch margin info, converting float→Decimal."""
        self._ensure_connected()
        data = self._kite.margins()
        equity = data.get("equity", {})

        available_data = equity.get("available", {})
        used_data = equity.get("used", {})

        available = Decimal(str(available_data.get("net", 0)))
        used = Decimal(str(used_data.get("net", 0)))

        logger.info(
            "zerodha.margins_fetched",
            available=str(available),
            used=str(used),
        )
        return MarginInfo(available=available, used=used, total=available + used)

    async def is_connected(self) -> bool:
        """Check if KiteConnect session is alive."""
        if self._kite is None:
            return False
        try:
            self._kite.profile()
            return True
        except Exception:
            return False

    async def get_ltp(self, instruments: list[str]) -> dict[str, Decimal]:
        """Get last traded prices. instruments format: 'NFO:NIFTY25JUNFUT'."""
        self._ensure_connected()
        data = self._kite.ltp(*instruments)
        return {
            key: Decimal(str(val.get("last_price", 0)))
            for key, val in data.items()
        }

    async def get_historical_data(
        self,
        instrument_token: int,
        from_date: datetime,
        to_date: datetime,
        interval: str = "5minute",
        continuous: bool = False,
        oi: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch historical candles from Zerodha."""
        self._ensure_connected()
        candles = self._kite.historical_data(
            instrument_token=instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=interval,
            continuous=continuous,
            oi=oi,
        )
        return [
            {
                "date": c.get("date"),
                "open": Decimal(str(c.get("open", 0))),
                "high": Decimal(str(c.get("high", 0))),
                "low": Decimal(str(c.get("low", 0))),
                "close": Decimal(str(c.get("close", 0))),
                "volume": c.get("volume", 0),
                **({"oi": c.get("oi", 0)} if oi else {}),
            }
            for c in candles
        ]

    async def trigger_kill_switch_cancel_all(self) -> list[BrokerOrderResult]:
        """Emergency: cancel all open orders (for KILL level)."""
        logger.critical("zerodha.kill_switch_cancel_all")
        return await self.cancel_all_orders()

    def _ensure_connected(self) -> None:
        """Raise if KiteConnect is not initialized."""
        if self._kite is None:
            raise RuntimeError(
                "Zerodha KiteConnect not initialized. "
                "Call authenticate() first."
            )
