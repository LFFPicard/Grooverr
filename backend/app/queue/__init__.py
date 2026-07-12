"""
Queue system & background workers (Batch 4, grooverr.md Section 10).

QueueItem rows in SQLite are the single source of truth (Section 9.3):
workers claim queued jobs, job state is persisted on every meaningful
update, and an SSE hub pushes state changes to the UI. A container
restart loses nothing — stuck jobs are reset to queued on boot.
"""
from app.queue.hub import QueueEventHub, hub
from app.queue.service import QueueService
from app.queue.workers import WorkerPool

__all__ = ["QueueEventHub", "hub", "QueueService", "WorkerPool"]
