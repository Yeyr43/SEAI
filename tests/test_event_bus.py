"""
测试 SEAI 事件总线
"""
import asyncio
import pytest
from seai.core.event_bus import AsyncEventBus, Event, EventPriority


class TestEventBus:
    def setup_method(self):
        self.bus = AsyncEventBus(max_history=100)

    def test_subscribe_and_publish(self):
        received = []

        async def handler(event):
            received.append(event)

        self.bus.subscribe("test.event", handler)

        event = Event(event_type="test.event", source="test", data={"key": "value"})
        asyncio.run(self.bus.publish_sync(event))

        assert len(received) == 1
        assert received[0].event_type == "test.event"
        assert received[0].data["key"] == "value"

    def test_wildcard_subscription(self):
        received = []

        async def handler(event):
            received.append(event)

        self.bus.subscribe_pattern("test.*", handler)

        event1 = Event(event_type="test.foo", source="test")
        event2 = Event(event_type="test.bar", source="test")
        event3 = Event(event_type="other.event", source="test")

        asyncio.run(self.bus.publish_sync(event1))
        asyncio.run(self.bus.publish_sync(event2))
        asyncio.run(self.bus.publish_sync(event3))

        assert len(received) == 2

    def test_unsubscribe(self):
        received = []

        async def handler(event):
            received.append(event)

        self.bus.subscribe("test.event", handler)
        self.bus.unsubscribe("test.event", handler)

        event = Event(event_type="test.event", source="test")
        asyncio.run(self.bus.publish_sync(event))

        assert len(received) == 0

    def test_event_history(self):
        for i in range(5):
            event = Event(event_type="test.event", source="test", data={"index": i})
            asyncio.run(self.bus.publish_sync(event))

        history = self.bus.get_history("test.event")
        assert len(history) == 5
        assert history[0].data["index"] == 0
        assert history[4].data["index"] == 4

    def test_event_priority(self):
        event = Event(
            event_type="test.event",
            source="test",
            priority=EventPriority.CRITICAL,
        )
        assert event.priority == EventPriority.CRITICAL
        assert event.to_dict()["priority"] == "critical"

    def test_event_to_dict(self):
        event = Event(
            event_type="test.event",
            source="test",
            data={"key": "value"},
            correlation_id="corr-123",
        )
        d = event.to_dict()
        assert d["event_type"] == "test.event"
        assert d["source"] == "test"
        assert d["data"]["key"] == "value"
        assert d["correlation_id"] == "corr-123"

    def test_handler_exception_isolation(self):
        received = []

        async def good_handler(event):
            received.append("good")

        async def bad_handler(event):
            raise RuntimeError("handler error")

        self.bus.subscribe("test.event", bad_handler)
        self.bus.subscribe("test.event", good_handler)

        event = Event(event_type="test.event", source="test")
        asyncio.run(self.bus.publish_sync(event))

        assert len(received) == 1
        assert received[0] == "good"

    def test_get_stats(self):
        self.bus.subscribe("test.event", lambda e: None)
        self.bus.subscribe_pattern("test.*", lambda e: None)

        stats = self.bus.get_stats()
        assert stats["subscriber_count"] == 1
        assert stats["wildcard_patterns"] == 1
        assert "test.event" in stats["event_types"]

    def test_match_pattern(self):
        assert AsyncEventBus._match_pattern("test.foo.bar", "test.*")
        assert AsyncEventBus._match_pattern("test.foo", "*.foo")
        assert AsyncEventBus._match_pattern("test.foo", "test.foo")
        assert not AsyncEventBus._match_pattern("other.foo", "test.*")
        assert AsyncEventBus._match_pattern("anything", "*")

    def test_shutdown(self):
        asyncio.run(self.bus.shutdown())
        assert self.bus._processor_task is None or self.bus._processor_task.done()