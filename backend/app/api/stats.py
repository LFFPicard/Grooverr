"""
Dashboard stat row (Section 9.5: aggregate queries, never N+1 per stat).

Two aggregate queries total: one SUM(CASE) sweep over queueitem, one over
album⋈track for library size + incomplete-album count.
"""
from fastapi import APIRouter
from sqlalchemy import case, func
from sqlmodel import Session, select

from app.api.schemas import StatsOut
from app.db import engine
from app.models import Album, JobStatus, JobType, QueueItem, Track, TrackStatus

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("", response_model=StatsOut)
def stats():
    with Session(engine) as session:
        downloading, queued, errored = session.exec(
            select(
                func.coalesce(func.sum(case(
                    (
                        (QueueItem.status == JobStatus.active)
                        & (QueueItem.job_type == JobType.download), 1
                    ), else_=0)), 0),
                func.coalesce(func.sum(case(
                    (QueueItem.status == JobStatus.queued, 1), else_=0)), 0),
                func.coalesce(func.sum(case(
                    (QueueItem.status == JobStatus.error, 1), else_=0)), 0),
            )
        ).one()

        downloaded_expr = func.coalesce(
            func.sum(case((Track.status == TrackStatus.downloaded, 1), else_=0)), 0
        )
        expected_expr = func.coalesce(Album.total_tracks, func.count(Track.id))
        per_album = (
            select(
                downloaded_expr.label("downloaded"),
                expected_expr.label("expected"),
            )
            .select_from(Album)
            .outerjoin(Track, Track.album_id == Album.id)  # type: ignore[arg-type]
            .group_by(Album.id)
            .subquery()
        )
        library_tracks, library_albums, incomplete = session.exec(
            select(
                func.coalesce(func.sum(per_album.c.downloaded), 0),
                func.count(),
                func.coalesce(func.sum(case(
                    (per_album.c.downloaded < per_album.c.expected, 1), else_=0)), 0),
            ).select_from(per_album)
        ).one()

    return StatsOut(
        downloading=downloading,
        queued=queued,
        errored_jobs=errored,
        library_tracks=library_tracks,
        library_albums=library_albums,
        incomplete_albums=incomplete,
    )
