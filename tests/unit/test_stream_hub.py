"""
The shared live-stream hub.

The behaviour that matters: one Kafka consumer per *topic being watched*,
however many viewers it has. Every viewer used to get its own consumer, so the
live stream's cost scaled with traffic instead of with the market list.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.kafka.stream_hub import StreamHub, Subscription


class FakeTopicStream:
    """Stands in for _TopicStream so no broker is needed."""

    instances: list["FakeTopicStream"] = []

    def __init__(self, topic):
        self.topic = topic
        self.subscribers = set()
        self.started = False
        self.stopped = False
        FakeTopicStream.instances.append(self)

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def deliver(self, payload):
        for subscriber in tuple(self.subscribers):
            subscriber.offer(payload)


@pytest.fixture
def hub():
    FakeTopicStream.instances = []
    with patch("app.kafka.stream_hub._TopicStream", FakeTopicStream):
        yield StreamHub(queue_maxsize=5)


async def test_two_subscribers_on_one_topic_share_a_single_consumer(hub):
    await hub.subscribe(["binance.BTCUSD.candles"])
    await hub.subscribe(["binance.BTCUSD.candles"])

    assert hub.consumer_count == 1
    assert len(FakeTopicStream.instances) == 1
    assert hub.subscriber_count("binance.BTCUSD.candles") == 2


async def test_a_viewer_watching_every_exchange_joins_each_topic(hub):
    topics = ["binance.BTCUSD.candles", "kraken.BTCUSD.candles", "coinbase.BTCUSD.candles"]
    await hub.subscribe(topics)

    assert hub.consumer_count == 3
    for topic in topics:
        assert hub.subscriber_count(topic) == 1


async def test_the_consumer_stops_when_the_last_subscriber_leaves(hub):
    first = await hub.subscribe(["binance.BTCUSD.candles"])
    second = await hub.subscribe(["binance.BTCUSD.candles"])
    stream = FakeTopicStream.instances[0]

    await hub.unsubscribe(first)
    assert hub.consumer_count == 1          # still one subscriber left
    assert not stream.stopped

    await hub.unsubscribe(second)
    assert hub.consumer_count == 0
    assert stream.stopped


async def test_unsubscribing_twice_is_harmless(hub):
    subscription = await hub.subscribe(["binance.BTCUSD.candles"])
    await hub.unsubscribe(subscription)
    await hub.unsubscribe(subscription)     # must not raise or double-decrement
    assert hub.consumer_count == 0


async def test_a_message_reaches_every_subscriber(hub):
    a = await hub.subscribe(["binance.BTCUSD.candles"])
    b = await hub.subscribe(["binance.BTCUSD.candles"])

    FakeTopicStream.instances[0].deliver({"close_price": "65000.00000000"})

    assert a.queue.get_nowait() == {"close_price": "65000.00000000"}
    assert b.queue.get_nowait() == {"close_price": "65000.00000000"}


async def test_duplicate_topics_in_one_subscription_are_collapsed(hub):
    subscription = await hub.subscribe(
        ["binance.BTCUSD.candles", "binance.BTCUSD.candles"]
    )
    assert subscription.topics == ("binance.BTCUSD.candles",)
    assert hub.subscriber_count("binance.BTCUSD.candles") == 1


async def test_a_failed_consumer_start_does_not_leave_a_dead_stream_registered(hub):
    with patch.object(FakeTopicStream, "start", AsyncMock(side_effect=RuntimeError("broker down"))):
        with pytest.raises(RuntimeError):
            await hub.subscribe(["binance.BTCUSD.candles"])

    # A half-started stream left in the registry would silently never deliver
    # anything to the next subscriber that joined it.
    assert hub.consumer_count == 0


async def test_close_stops_every_consumer(hub):
    await hub.subscribe(["binance.BTCUSD.candles"])
    await hub.subscribe(["kraken.ETHUSD.candles"])

    await hub.close()

    assert hub.consumer_count == 0
    assert all(stream.stopped for stream in FakeTopicStream.instances)


# ── Back-pressure ────────────────────────────────────────────────────────────

def test_a_slow_subscriber_drops_its_oldest_messages_instead_of_growing():
    """
    An unbounded per-subscriber queue turns one stalled browser into a memory
    leak that takes the whole process down.
    """
    subscription = Subscription(("binance.BTCUSD.candles",), maxsize=3)

    for i in range(6):
        subscription.offer({"n": i})

    assert subscription.queue.qsize() == 3
    assert subscription.dropped == 3
    # The newest messages survive — a live price feed's old values are useless.
    assert [subscription.queue.get_nowait()["n"] for _ in range(3)] == [3, 4, 5]


def test_offer_never_blocks_the_shared_reader():
    """One slow client must not stall delivery to everyone else on the topic."""
    subscription = Subscription(("t",), maxsize=1)
    for i in range(100):
        subscription.offer({"n": i})        # would deadlock if it awaited
    assert subscription.queue.qsize() == 1
