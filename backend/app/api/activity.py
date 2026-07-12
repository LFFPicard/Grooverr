"""
Recent-activity feed — Dashboard's "Recent Activity" panel (Section 8).

Not a paginated resource: always just the latest N finished/errored queue
jobs, newest first. A dedicated small query rather than overloading the
main queue listing, which is filtered/sorted for the live "active queue"
use case instead.
"""
from fastapi import APIRouter
from sqlmodel import Session, select

from app.api.schemas import ActivityFeedOut, ActivityItemOut
from app.db import engine
from app.models import Album, Artist, JobStatus, QueueItem, Track

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=ActivityFeedOut)
def recent_activity(limit: int = 20):
    limit = max(1, min(limit, 100))
    with Session(engine) as session:
        query = (
            select(QueueItem, Track, Album, Artist)
            .where(QueueItem.status.in_((JobStatus.done, JobStatus.error)))  # type: ignore[attr-defined]
            .join(Track, Track.id == QueueItem.track_id, isouter=True)
            .join(Album, Album.id == Track.album_id, isouter=True)
            .join(Artist, Artist.id == Album.artist_id, isouter=True)
            .order_by(QueueItem.finished_at.desc())  # type: ignore[attr-defined]
            .limit(limit)
        )
        rows = session.exec(query).all()
        items = [
            ActivityItemOut(
                id=job.id,
                job_type=job.job_type.value,
                status=job.status.value,
                track_title=track.title if track else None,
                artist_name=artist.name if artist else None,
                album_title=album.title if album else None,
                error_message=job.error_message,
                occurred_at=job.finished_at or job.created_at,
            )
            for job, track, album, artist in rows
        ]
    return ActivityFeedOut(items=items)
