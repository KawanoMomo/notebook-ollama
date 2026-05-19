import asyncio

import pytest

from apps.api.sse import SseBroker


@pytest.mark.asyncio
async def test_subscribe_and_publish_delivers_to_each_subscriber():
    broker = SseBroker()
    sub1 = broker.subscribe("topic-a")
    sub2 = broker.subscribe("topic-a")
    await broker.publish("topic-a", {"event": "x"})
    m1 = await asyncio.wait_for(sub1.get(), timeout=0.2)
    m2 = await asyncio.wait_for(sub2.get(), timeout=0.2)
    assert m1 == {"event": "x"}
    assert m2 == {"event": "x"}


@pytest.mark.asyncio
async def test_publish_to_unrelated_topic_does_not_deliver():
    broker = SseBroker()
    sub = broker.subscribe("a")
    await broker.publish("b", {"event": "y"})
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.1)


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue():
    broker = SseBroker()
    sub = broker.subscribe("t")
    broker.unsubscribe("t", sub)
    await broker.publish("t", {"event": "z"})  # must not raise
