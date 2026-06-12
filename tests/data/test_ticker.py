"""Tests for src/data/ticker.py — WebSocket TickerManager."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from src.data.providers import Tick
from src.data.ticker import TickerManager


@pytest.fixture
def collected_ticks() -> list:
    return []


@pytest.fixture
def ticker(collected_ticks: list) -> TickerManager:
    return TickerManager(
        api_key="test_key",
        access_token="test_token",
        on_tick=collected_ticks.extend,
        on_connect=lambda: None,
        on_disconnect=lambda: None,
    )


class TestTickerManager:
    def test_initial_state(self, ticker: TickerManager) -> None:
        assert ticker.is_connected is False
        assert ticker.subscription_count == 0

    def test_subscribe_not_connected(self, ticker: TickerManager) -> None:
        results = ticker.subscribe([12345, 67890])
        assert results[12345] is False
        assert results[67890] is False

    @patch("src.data.ticker._import_kite_ticker")
    def test_start_creates_connection(
        self, mock_import: MagicMock, ticker: TickerManager
    ) -> None:
        mock_kss_instance = MagicMock()
        mock_import.return_value.return_value = mock_kss_instance
        ticker._subscriptions = {12345: 0}
        ticker.start()
        mock_import.assert_called_once()
        mock_kss_instance.connect.assert_called_once_with(threaded=True)

    def test_on_ticks_callback_converts(
        self, ticker: TickerManager, collected_ticks: list
    ) -> None:
        raw_ticks = [
            {
                "instrument_token": 12345,
                "timestamp": datetime(2025, 6, 25, 9, 15, tzinfo=UTC),
                "last_price": 24050.5,
                "last_quantity": 50,
                "volume": 1000000,
                "average_price": 24040.25,
            },
        ]
        ticker._on_ticks_callback(MagicMock(), raw_ticks)
        assert len(collected_ticks) == 1
        assert isinstance(collected_ticks[0], Tick)
        assert collected_ticks[0].instrument_token == 12345
        assert collected_ticks[0].last_price == Decimal("24050.5")

    def test_on_ticks_ignores_bad_ticks(
        self, ticker: TickerManager, collected_ticks: list
    ) -> None:
        raw_ticks = [
            {
                "instrument_token": 12345,
                "timestamp": datetime(2025, 6, 25, 9, 15, tzinfo=UTC),
                "last_price": 100,
                "last_quantity": 10,
                "volume": 5000,
                "average_price": 99,
            },
            {"no_instrument_token": True},
        ]
        ticker._on_ticks_callback(MagicMock(), raw_ticks)
        assert len(collected_ticks) == 1

    def test_on_connect_sets_connected(self, ticker: TickerManager) -> None:
        ticker._connected = False
        ticker._on_connect_callback(MagicMock())
        assert ticker.is_connected is True

    def test_on_disconnect_sets_disconnected(self, ticker: TickerManager) -> None:
        ticker._connected = True
        ticker._on_disconnect_callback(MagicMock(), 1000, "test")
        assert ticker.is_connected is False

    def test_on_error_callback(self, ticker: TickerManager) -> None:
        errors = []
        error_ticker = TickerManager(
            api_key="k",
            access_token="t",
            on_error=errors.append,
        )
        error_ticker._on_error_callback(MagicMock(), 1001, "test error")
        assert len(errors) == 1

    def test_on_noreconnect(self, ticker: TickerManager) -> None:
        errors = []
        nr_ticker = TickerManager(
            api_key="k",
            access_token="t",
            on_error=errors.append,
        )
        nr_ticker._connected = True
        nr_ticker._on_noreconnect_callback(MagicMock())
        assert nr_ticker.is_connected is False
        assert len(errors) == 1

    def test_subscribe_with_mock_kite(self, ticker: TickerManager) -> None:
        mock_kss = MagicMock()
        ticker._kite_tickers = [mock_kss]
        results = ticker.subscribe([12345, 67890])
        assert results[12345] is True
        assert results[67890] is True
        assert ticker.subscription_count == 2
        mock_kss.subscribe.assert_called()

    def test_subscribe_duplicate_tokens(self, ticker: TickerManager) -> None:
        mock_kss = MagicMock()
        ticker._kite_tickers = [mock_kss]
        ticker.subscribe([12345])
        results = ticker.subscribe([12345, 67890])
        assert results[12345] is True
        assert ticker.subscription_count == 2

    def test_subscribe_respects_limit(self, ticker: TickerManager) -> None:
        mock_kss = MagicMock()
        ticker._kite_tickers = [mock_kss]
        ticker._max_subs_per_connection = 2
        ticker.subscribe([111, 222])
        results = ticker.subscribe([333])
        assert results[333] is False

    def test_unsubscribe(self, ticker: TickerManager) -> None:
        mock_kss = MagicMock()
        ticker._kite_tickers = [mock_kss]
        ticker.subscribe([12345, 67890])
        ticker.unsubscribe([12345])
        assert ticker.subscription_count == 1

    def test_stop_closes_connections(self, ticker: TickerManager) -> None:
        mock_kss = MagicMock()
        ticker._kite_tickers = [mock_kss]
        ticker._connected = True
        ticker.stop()
        assert ticker.is_connected is False
        assert len(ticker._kite_tickers) == 0
