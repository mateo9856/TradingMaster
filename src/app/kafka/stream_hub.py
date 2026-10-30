"""
One Kafka consumer per topic, shared by every live-stream subscriber.

Before this, each WebSocket connection built its own `AIOKafkaConsumer`. The
cost of the live stream therefore scaled with the number of *viewers*: 200
people watching BTC/USD meant 200 consumers, 200 broker connections and 200
copies of every message decoded in this process, for one underlying stream.

Here a topic is consumed once, however many subscribers it has, so the cost
scales with the number of *markets being watched* — bounded by the market list
(~50), not by traffic. Subscribers are reference-counted: the consumer starts
with the first and stops with the last.

Back-pressure: each subscriber has a bounded queue. A client that cannot keep
up loses its oldest buffered candles rather than growing a queue without limit
and taking the process down with it. Drops are counted, and a subscriber that
keeps falling behind is dropped so it can reconnect.

Per-process, like the rate limiter — with several API replicas each holds its
own consumers, which is fine: they are independent readers of the same topics.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Iterable

from aiokafka import AIOKafkaConsumer

from app.config import KAFKA_BOOTSTRAP_SERVERS, WS_QUEUE_MAXSIZE
from app.metrics import (
    stream_hub_consumers,
    stream_hub_subscribers,
    websocket_messages_dropped_total,
)

logger = logging.getLogger(__name__)


class Subscription:
    """One subscriber's view of one or more topics."""

    def __init__(self, topics: tuple[str, ...], maxsize: int):
        self.topics = topics
        self.queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def offer(self, payload: dict) -> None:
        """
        Hand a message to this subscriber, dropping its oldest if it is full.

        Never blocks: one slow browser must not stall the shared reader task
        and therefore every other subscriber on the topic.
        """
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()          # discard the oldest
            except asyncio.QueueEmpty:           # drained concurrently
                pass
            self.dropped += 1
            websocket_messages_dropped_total.inc()
            try:
                self.queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def __aiter__(self) -> AsyncIterator[dict]:
        while True:
            yield await self.queue.get()


class _TopicStream:
    """One Kafka consumer for one topic, fanning out to its subscribers."""

    def __init__(self, topic: str):
        self.topic = topic
        self.subscribers: set[Subscription] = set()
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=None,              # no consumer group: always read the latest
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        self._task = asyncio.create_task(self._read(), name=f"stream-hub:{self.topic}")
        stream_hub_consumers.inc()
        logger.debug(f"Stream hub: started consumer for {self.topic}")

    async def _read(self) -> None:
        assert self._consumer is not None
        try:
            async for message in self._consumer:
                try:
                    payload = json.loads(message.value.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    logger.warning(f"Stream hub: undecodable message on {self.topic}")
                    continue
                for subscriber in tuple(self.subscribers):
                    subscriber.offer(payload)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(f"Stream hub: reader for {self.topic} stopped: {error!r}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._consumer is not None:
            try:
                await self._consumer.stop()
            finally:
                self._consumer = None
                stream_hub_consumers.dec()
        logger.debug(f"Stream hub: stopped consumer for {self.topic}")


class StreamHub:
    """Process-wide registry of topic streams."""

    def __init__(self, queue_maxsize: int = WS_QUEUE_MAXSIZE):
        self._streams: dict[str, _TopicStream] = {}
        self._lock = asyncio.Lock()
        self._queue_maxsize = queue_maxsize

    @property
    def consumer_count(self) -> int:
        return len(self._streams)

    def subscriber_count(self, topic: str) -> int:
        stream = self._streams.get(topic)
        return len(stream.subscribers) if stream else 0

    async def subscribe(self, topics: Iterable[str]) -> Subscription:
        """Attach to every topic, starting consumers that aren't running yet."""
        topics = tuple(dict.fromkeys(topics))       # de-duplicate, keep order
        subscription = Subscription(topics, self._queue_maxsize)

        async with self._lock:
            for topic in topics:
                stream = self._streams.get(topic)
                if stream is None:
                    stream = _TopicStream(topic)
                    self._streams[topic] = stream
                    try:
                        await stream.start()
                    except Exception:
                        # Don't leave a half-started stream in the registry, or
                        # the next subscriber joins something that never reads.
                        self._streams.pop(topic, None)
                        await self._detach(subscription, lock_held=True)
                        raise
                stream.subscribers.add(subscription)
                stream_hub_subscribers.inc()

        return subscription

    async def unsubscribe(self, subscription: Subscription) -> None:
        async with self._lock:
            await self._detach(subscription, lock_held=True)

    async def _detach(self, subscription: Subscription, lock_held: bool = False) -> None:
        for topic in subscription.topics:
            stream = self._streams.get(topic)
            if stream is None or subscription not in stream.subscribers:
                continue
            stream.subscribers.discard(subscription)
            stream_hub_subscribers.dec()
            if not stream.subscribers:
                # Last subscriber left — nothing to feed, so stop reading.
                self._streams.pop(topic, None)
                await stream.stop()

    async def close(self) -> None:
        """Stop every consumer — called from the app's shutdown."""
        async with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
            for stream in streams:
                stream.subscribers.clear()
                await stream.stop()
        stream_hub_subscribers.set(0)


# The process-wide instance the WebSocket endpoint uses.
stream_hub = StreamHub()
