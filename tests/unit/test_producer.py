"""
Unit tests for the Kafka producer.
All external dependencies (CCXT, AIOKafkaProducer) are mocked —
no real exchange connection or Kafka broker needed.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.kafka.producer import _topic_name, _stream_exchange, run_producer


class TestTopicName:

    def test_btc_usdt(self):
        assert _topic_name("binance", "BTC/USDT") == "binance.BTCUSDT.candles"

    def test_eth_usdt(self):
        assert _topic_name("kraken", "ETH/USDT") == "kraken.ETHUSDT.candles"

    def test_exchange_preserved(self):
        assert _topic_name("coinbase", "BTC/USDT").startswith("coinbase.")

    def test_slash_removed_from_ticker(self):
        topic = _topic_name("binance", "BNB/USDT")
        assert "/" not in topic


class TestStreamExchange:

    async def test_sends_candle_to_correct_topic(self):
        """Single candle tick flows correctly through to Kafka producer."""
        # Fake OHLCV data returned by CCXT watch_ohlcv_for_symbols
        fake_ohlcv = {
            "BTC/USDT": [[1_700_000_000_000, 65000.0, 65300.0, 64850.0, 65200.0, 15.4]]
        }

        mock_exchange = AsyncMock()
        # First call returns data, second raises to break the loop
        mock_exchange.watch_ohlcv_for_symbols.side_effect = [
            fake_ohlcv,
            Exception("stop loop"),
        ]
        mock_exchange.close = AsyncMock()

        mock_producer = AsyncMock()

        with patch("app.kafka.producer.ccxtpro") as mock_ccxtpro:
            mock_ccxtpro.binance.return_value = mock_exchange

            # Should complete without raising after the second iteration breaks
            try:
                await _stream_exchange("binance", ["BTC/USDT"], mock_producer)
            except Exception:
                pass

        # Verify Kafka producer was called with correct topic and payload
        assert mock_producer.send.called
        call_args = mock_producer.send.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[1]["value"].decode("utf-8"))

        assert topic == "binance.BTCUSDT.candles"
        assert payload["exchange"] == "binance"
        assert payload["ticker"] == "BTC/USDT"
        assert payload["open_price"] == 65000.0
        assert payload["close_price"] == 65200.0
        assert payload["volume"] == 15.4

    async def test_reconnects_on_error(self):
        """Stream reconnects automatically after an exception."""
        mock_exchange = AsyncMock()
        mock_exchange.watch_ohlcv_for_symbols.side_effect = [
            Exception("connection lost"),  # first call fails
            Exception("stop loop"),        # second call stops the test
        ]
        mock_exchange.close = AsyncMock()
        mock_producer = AsyncMock()

        with patch("app.kafka.producer.ccxtpro") as mock_ccxtpro:
            mock_ccxtpro.binance.return_value = mock_exchange
            with patch("app.kafka.producer.asyncio.sleep", new_callable=AsyncMock):
                try:
                    await _stream_exchange("binance", ["BTC/USDT"], mock_producer)
                except Exception:
                    pass

        # watch_ohlcv_for_symbols was called twice — confirms reconnect happened
        assert mock_exchange.watch_ohlcv_for_symbols.call_count == 2

    async def test_exchange_closed_on_error(self):
        """Exchange connection is always closed after an error."""
        mock_exchange = AsyncMock()
        mock_exchange.watch_ohlcv_for_symbols.side_effect = Exception("stop")
        mock_exchange.close = AsyncMock()
        mock_producer = AsyncMock()

        with patch("app.kafka.producer.ccxtpro") as mock_ccxtpro:
            mock_ccxtpro.binance.return_value = mock_exchange
            with patch("app.kafka.producer.asyncio.sleep", new_callable=AsyncMock):
                try:
                    await _stream_exchange("binance", ["BTC/USDT"], mock_producer)
                except Exception:
                    pass

        mock_exchange.close.assert_called()


class TestRunProducer:

    async def test_starts_one_task_per_exchange(self):
        """run_producer spawns one streaming coroutine per configured exchange."""
        with patch("app.kafka.producer.WATCH_EXCHANGES", ["binance", "kraken"]):
            with patch("app.kafka.producer.AIOKafkaProducer") as mock_kafka:
                mock_producer_instance = AsyncMock()
                mock_kafka.return_value = mock_producer_instance

                with patch("app.kafka.producer._stream_exchange", new_callable=AsyncMock) as mock_stream:
                    await run_producer()

                # One call per exchange
                assert mock_stream.call_count == 2
                exchanges_called = {c.args[0] for c in mock_stream.call_args_list}
                assert exchanges_called == {"binance", "kraken"}

    async def test_producer_stopped_on_completion(self):
        """Kafka producer is always stopped even if streaming finishes."""
        with patch("app.kafka.producer.WATCH_EXCHANGES", ["binance"]):
            with patch("app.kafka.producer.AIOKafkaProducer") as mock_kafka:
                mock_producer_instance = AsyncMock()
                mock_kafka.return_value = mock_producer_instance

                with patch("app.kafka.producer._stream_exchange", new_callable=AsyncMock):
                    await run_producer()

                mock_producer_instance.stop.assert_called_once()