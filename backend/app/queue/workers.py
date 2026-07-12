"""
Async worker pool (Section 9.3): N asyncio tasks inside the FastAPI
process pulling from the QueueItem table. Workers sleep on a shared
asyncio.Event with a 5-second poll fallback — no busy-looping against the
DB. Concurrency comes from the download_concurrency setting (default 3).

On graceful shutdown a worker cancelled mid-job releases the job back to
'queued'; on an unclean shutdown the startup recovery pass does the same.
"""
import asyncio
import contextlib
import logging
from typing import Optional

from app.queue.pipeline import Pipeline
from app.queue.service import QueueService

logger = logging.getLogger("grooverr.workers")

POLL_INTERVAL_SECONDS = 5.0


class WorkerPool:
    def __init__(self, queue: QueueService, pipeline: Optional[Pipeline] = None,
                 concurrency: Optional[int] = None):
        self.queue = queue
        self.pipeline = pipeline or Pipeline(queue)
        if concurrency is None:
            from app.settings_store import get_setting
            concurrency = int(get_setting("download_concurrency") or 3)
        self.concurrency = max(1, concurrency)
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        recovered = self.queue.recover_stuck_jobs()
        if recovered:
            logger.info("Startup recovery: %d stuck job(s) reset to queued", recovered)
        self._tasks = [
            asyncio.create_task(self._worker(i), name=f"grooverr-worker-{i}")
            for i in range(self.concurrency)
        ]
        logger.info("Worker pool started (%d workers)", self.concurrency)

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        logger.info("Worker pool stopped")

    async def _worker(self, index: int) -> None:
        while True:
            job = self.queue.claim_next()
            if job is None:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.queue.wake.wait(), POLL_INTERVAL_SECONDS)
                self.queue.wake.clear()
                continue
            logger.info("Worker %d picked up %s job %s", index, job.job_type.value, job.id)
            try:
                await self.pipeline.process(job)
            except asyncio.CancelledError:
                # Graceful shutdown mid-job: hand the job back before dying.
                self.queue.release_to_queue(job.id)
                raise
