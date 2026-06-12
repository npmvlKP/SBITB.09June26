"""WebSocket ticker manager for Zerodha KiteTicker.

Manages real-time market data feeds via WebSocket with:
- Auto-reconnect on disconnect
- Callback dispatch (tick, connect, disconnect, error, close)
- Subscription management within Zerodha limits (3000 subs/connection, 3 connections)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import structlog

from src.data.providers import Tick

logger = structlog.get_logger(__name__)

_MAX_SUBS_PER_CONNECTION = 3000
_MAX_CONNECTIONS = 3
_RECONNECT_DELAY_SECONDS = 5
_MAX_RECONNECT_ATTEMPTS = 10

IST = timezone(timedelta(hours=5, minutes=30))


class TickerManager:
    """Manages Zerodha KiteTicker WebSocket connections.

    Handles subscription distribution across connections,
    auto-reconnect, and callback dispatch to consumers.
    """

    def __init__(
        self,
        api_key: str,
        access_token: str,
        on_tick: Callable[[list[Tick]], None] | None = None,
        on_connect: Callable[[], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        on_error: Callable[[Any], None] | None = None,
        on_close: Callable[[], None] | None = None,
        max_subs_per_connection: int = _MAX_SUBS_PER_CONNECTION,
        max_connections: int = _MAX_CONNECTIONS,
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._on_tick = on_tick
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_error = on_error
        self._on_close = on_close
        self._max_subs_per_connection = max_subs_per_connection
        self._max_connections = max_connections
        self._kite_tickers: list[Any] = []
        self._subscriptions: dict[int, int] = {}
        self._connected = False
        self._reconnect_attempts = 0

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)

    def start(self) -> None:
        """Start the WebSocket ticker connection."""
        kite_ticker_cls = _import_kite_ticker()
        kss = kite_ticker_cls(
            api_key=self._api_key,
            access_token=self._access_token,
        )
        kss.on_ticks = self._on_ticks_callback
        kss.on_connect = self._on_connect_callback
        kss.on_disconnect = self._on_disconnect_callback
        kss.on_error = self._on_error_callback
        kss.on_close = self._on_close_callback
        kss.on_reconnect = self._on_reconnect_callback
        kss.on_noreconnect = self._on_noreconnect_callback
        self._kite_tickers = [kss]
        kss.connect(threaded=True)
        logger.info("ticker.started")

    def stop(self) -> None:
        """Stop all WebSocket connections."""
        for kss in self._kite_tickers:
            try:
                kss.close()
            except Exception as exc:
                logger.warning("ticker.close_error", error=str(exc))
        self._kite_tickers = []
        self._connected = False
        logger.info("ticker.stopped")

    def subscribe(self, instrument_tokens: list[int]) -> dict[int, bool]:
        """Subscribe to real-time ticks for given tokens.

        Returns dict mapping token → success.
        Respects per-connection subscription limits.
        """
        results: dict[int, bool] = {}
        if not self._kite_tickers:
            logger.warning("ticker.not_connected_cannot_subscribe")
            for t in instrument_tokens:
                results[t] = False
            return results

        current_ticker = self._kite_tickers[0]
        current_subs = len(self._subscriptions)

        for token in instrument_tokens:
            if token in self._subscriptions:
                results[token] = True
                continue
            if current_subs >= self._max_subs_per_connection:
                logger.warning(
                    "ticker.sub_limit_reached",
                    token=token,
                    limit=self._max_subs_per_connection,
                )
                results[token] = False
                continue
            try:
                current_ticker.subscribe([token])
                self._subscriptions[token] = 0
                current_subs += 1
                results[token] = True
            except Exception as exc:
                logger.error(
                    "ticker.subscribe_failed",
                    token=token,
                    error=str(exc),
                )
                results[token] = False
        logger.info(
            "ticker.subscribed",
            total_subs=len(self._subscriptions),
            new_count=len([v for v in results.values() if v]),
        )
        return results

    def unsubscribe(self, instrument_tokens: list[int]) -> None:
        """Unsubscribe from real-time ticks for given tokens."""
        if not self._kite_tickers:
            return
        self._kite_tickers[0].unsubscribe(instrument_tokens)
        for token in instrument_tokens:
            self._subscriptions.pop(token, None)
        logger.info(
            "ticker.unsubscribed",
            tokens=instrument_tokens,
            remaining=len(self._subscriptions),
        )

    def set_mode(self, mode: str, instrument_tokens: list[int]) -> None:
        """Set streaming mode: 'quote' or 'full'."""
        if not self._kite_tickers:
            return
        self._kite_tickers[0].set_mode(mode, instrument_tokens)

    def _on_ticks_callback(self, kss: Any, ticks: list[dict[str, Any]]) -> None:
        """Convert raw KiteTicker ticks to our Tick DTO and dispatch."""
        parsed: list[Tick] = []
        for raw in ticks:
            try:
                token = raw.get("instrument_token", 0)
                if not token:
                    continue
                parsed.append(
                    Tick(
                        instrument_token=token,
                        timestamp=raw.get(
                            "timestamp",
                            datetime.now(tz=IST),
                        ),
                        last_price=Decimal(str(raw.get("last_price", 0))),
                        last_quantity=int(raw.get("last_quantity", 0)),
                        volume=int(raw.get("volume", 0)),
                        average_price=Decimal(str(raw.get("average_price", 0))),
                    )
                )
            except Exception as exc:
                logger.warning(
                    "ticker.tick_parse_error",
                    error=str(exc),
                )
        if parsed and self._on_tick is not None:
            self._on_tick(parsed)

    def _on_connect_callback(self, kss: Any) -> None:
        """Handle WebSocket connection established."""
        self._connected = True
        self._reconnect_attempts = 0
        if self._subscriptions:
            tokens = list(self._subscriptions.keys())
            kss.subscribe(tokens)
            logger.info(
                "ticker.reconnected_resubscribed",
                count=len(tokens),
            )
        logger.info("ticker.connected")
        if self._on_connect is not None:
            self._on_connect()

    def _on_disconnect_callback(self, kss: Any, code: int, reason: str) -> None:
        """Handle WebSocket disconnection."""
        self._connected = False
        logger.warning(
            "ticker.disconnected",
            code=code,
            reason=reason,
        )
        if self._on_disconnect is not None:
            self._on_disconnect()

    def _on_error_callback(self, kss: Any, code: int, message: str) -> None:
        """Handle WebSocket error."""
        logger.error(
            "ticker.error",
            code=code,
            message=message,
        )
        if self._on_error is not None:
            self._on_error(code)

    def _on_close_callback(self, kss: Any, code: int, reason: str) -> None:
        """Handle WebSocket close."""
        self._connected = False
        logger.info("ticker.closed", code=code, reason=reason)
        if self._on_close is not None:
            self._on_close()

    def _on_reconnect_callback(self, kss: Any, attempts: int, delay: float) -> None:
        """Handle WebSocket reconnect attempt."""
        self._reconnect_attempts = attempts
        logger.info(
            "ticker.reconnect_attempt",
            attempts=attempts,
            delay=delay,
        )

    def _on_noreconnect_callback(self, kss: Any) -> None:
        """Handle permanent reconnect failure."""
        self._connected = False
        logger.critical("ticker.noreconnect_exhausted")
        if self._on_error is not None:
            self._on_error("NO_RECONNECT")


def _import_kite_ticker() -> Any:
    """Import KiteTicker with deferred import to avoid hard dependency at module load."""
    try:
        from kiteconnect import KiteTicker  # noqa: PLC0415

        return KiteTicker
    except ImportError as exc:
        raise ImportError(
            "kiteconnect not installed. Run: pip install kiteconnect"
        ) from exc
