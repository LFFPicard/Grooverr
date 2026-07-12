"""
In-process pub/sub hub for queue state changes, feeding the SSE endpoint.

One-directional pushes (Section 4: SSE over WebSockets). Subscribers get a
bounded asyncio.Queue each; a slow/stalled consumer drops its oldest events
instead of back-pressuring the workers — the UI treats events as "something
changed" signals backed by refetch, so lossy delivery is fine.

publish() must be called from the event loop; publish_threadsafe() from
worker threads (yt-dlp progress hooks).
"""
import asyncio
import json
from typing import Any, Optional


class QueueEventHub:
    def __init__(self, max_queued_events: int = 256):
        self._subscribers: set[asyncio.Queue] = set()
        self._max = max_queued_events
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Remember the serving event loop so worker threads can publish."""
        self._loop = loop or asyncio.get_running_loop()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        payload = {"type": event_type, **data}
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()          # drop oldest, keep newest
                    queue.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def publish_threadsafe(self, event_type: str, data: dict[str, Any]) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self.publish, event_type, data)

    @staticmethod
    def format_sse(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# Process-wide hub instance (single-process app, Section 4 architecture).
hub = QueueEventHub()
