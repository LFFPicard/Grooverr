"""
Queue API endpoints (Batch 4 surface — the full REST layer is Batch 5).

POST /api/queue/add          — add a track by title/artist(/album); kicks off
                               the resolve → download pipeline
GET  /api/queue              — list jobs (basic status/type filters)
POST /api/queue/{id}/retry   — reset an errored job to queued
DELETE /api/queue/{id}       — cancel a queued job
GET  /api/queue/events       — SSE stream of queue state changes
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from app.api.schemas import Page, QueueItemOut
from app.db import engine
from app.downloader.ytdlp import SUPPORTED_FORMATS
from app.models import Album, Artist, JobStatus, JobType, QueueItem, Track
from app.queue.hub import hub

router = APIRouter(prefix="/api/queue", tags=["queue"])

KEEPALIVE_SECONDS = 15


def get_queue_service():
    from app import runtime
    return runtime.queue_service


class AddTrackRequest(BaseModel):
    title: str = Field(min_length=1)
    artist: Optional[str] = None
    album: Optional[str] = None
    quality_kbps: Optional[int] = Field(default=None, ge=32, le=320)
    output_format: Optional[str] = None


@router.post("/add", status_code=202)
def add_track(body: AddTrackRequest):
    if body.output_format and body.output_format not in SUPPORTED_FORMATS:
        raise HTTPException(
            422,
            f"Unsupported format {body.output_format!r} — supported: {', '.join(SUPPORTED_FORMATS)}",
        )
    track_id, job_id = get_queue_service().add_track_request(
        title=body.title,
        artist=body.artist,
        album=body.album,
        quality_kbps=body.quality_kbps,
        output_format=body.output_format,
    )
    return {"track_id": track_id, "job_id": job_id}


@router.get("", response_model=Page[QueueItemOut])
def list_jobs(
    status: Optional[JobStatus] = None,
    job_type: Optional[JobType] = None,
    limit: int = 100,
    offset: int = 0,
):
    limit = max(1, min(limit, 500))
    with Session(engine) as session:
        query = (
            select(QueueItem, Track, Album, Artist)
            .join(Track, Track.id == QueueItem.track_id, isouter=True)
            .join(Album, Album.id == Track.album_id, isouter=True)
            .join(Artist, Artist.id == Album.artist_id, isouter=True)
        )
        if status is not None:
            query = query.where(QueueItem.status == status)
        if job_type is not None:
            query = query.where(QueueItem.job_type == job_type)
        total = session.exec(
            select(func.count()).select_from(query.subquery())
        ).one()
        rows = session.exec(
            query.order_by(QueueItem.priority, QueueItem.created_at)
            .limit(limit)
            .offset(offset)
        ).all()
        items = [
            QueueItemOut(
                **job.model_dump(),
                track_title=track.title if track else None,
                track_status=track.status.value if track else None,
                artist_name=artist.name if artist else None,
                album_title=album.title if album else None,
            )
            for job, track, album, artist in rows
        ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/{job_id}/retry")
def retry_job(job_id: str):
    if not get_queue_service().retry(job_id):
        raise HTTPException(409, "Job is not in an error state (or does not exist)")
    return {"status": "queued"}


@router.delete("/{job_id}")
def cancel_job(job_id: str):
    if not get_queue_service().cancel(job_id):
        raise HTTPException(
            409, "Only queued jobs can be cancelled (job may be active, finished, or missing)"
        )
    return {"status": "cancelled"}


@router.get("/events")
async def queue_events(request: Request):
    """SSE stream — every queue state change as a JSON `data:` event, with
    keepalive comments so proxies don't drop the idle connection."""
    subscription = hub.subscribe()

    async def stream():
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(subscription.get(), KEEPALIVE_SECONDS)
                    yield hub.format_sse(payload)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            hub.unsubscribe(subscription)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
