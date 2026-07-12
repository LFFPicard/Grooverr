"""
Process-wide singletons shared by API routes and the worker pipeline.

One MetadataResolver (one MusicBrainz rate limiter for the whole process —
the 1 req/s policy is per client, so search endpoints and resolve workers
must share it) and one QueueService (one wake event for the worker pool).
"""
import logging

from app.queue.service import QueueService
from app.resolver.engine import MetadataResolver

queue_service = QueueService()
resolver = MetadataResolver()


def configure_logging() -> None:
    """Give grooverr.* loggers a handler so worker/pipeline lines appear in
    server output (uvicorn only configures its own loggers)."""
    logger = logging.getLogger("grooverr")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(levelname)s:     %(name)s: %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
