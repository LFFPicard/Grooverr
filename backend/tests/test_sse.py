"""SSE hub + endpoint tests."""
import asyncio
import json

from app.queue.hub import QueueEventHub


async def test_subscribe_publish_receive():
    hub = QueueEventHub()
    sub = hub.subscribe()
    hub.publish("queue_update", {"job": {"id": "j1", "status": "active"}})
    payload = await asyncio.wait_for(sub.get(), 1)
    assert payload["type"] == "queue_update"
    assert payload["job"]["id"] == "j1"
    hub.unsubscribe(sub)
    assert sub not in hub._subscribers


async def test_slow_subscriber_drops_oldest_not_newest():
    hub = QueueEventHub(max_queued_events=2)
    sub = hub.subscribe()
    for i in range(5):
        hub.publish("queue_update", {"n": i})
    received = [sub.get_nowait()["n"], sub.get_nowait()["n"]]
    assert received == [3, 4]                     # oldest dropped


async def test_publish_threadsafe_from_worker_thread():
    hub = QueueEventHub()
    hub.bind_loop()
    sub = hub.subscribe()

    def worker_thread():
        hub.publish_threadsafe("queue_update", {"job": {"id": "j2"}})

    await asyncio.to_thread(worker_thread)
    payload = await asyncio.wait_for(sub.get(), 1)
    assert payload["job"]["id"] == "j2"


def test_sse_wire_format():
    line = QueueEventHub.format_sse({"type": "queue_update", "job": {"id": "j1"}})
    assert line.startswith("data: ")
    assert line.endswith("\n\n")
    assert json.loads(line[len("data: "):].strip())["job"]["id"] == "j1"
