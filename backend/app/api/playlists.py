"""
Playlist endpoints (Section 5 Playlist/PlaylistTrack tables, added in the
Batch 6/7 review to give "Complete this playlist" (Section 7.4) something
to group against).
"""
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func
from sqlmodel import Session, select

from app.api.schemas import (
    CompletePlaylistResponse,
    Page,
    PlaylistDetail,
    PlaylistSummary,
    PlaylistTrackOut,
    TrackOut,
)
from app.db import engine
from app.models import Playlist, PlaylistTrack, Track, TrackStatus
from app import runtime

router = APIRouter(prefix="/api/library/playlists", tags=["playlists"])

_DOWNLOADED = func.coalesce(
    func.sum(case((Track.status == TrackStatus.downloaded, 1), else_=0)), 0
)
_KNOWN = func.count(Track.id)


def _completeness(downloaded: int, expected: int) -> str:
    if downloaded <= 0:
        return "empty"
    return "complete" if downloaded >= expected else "incomplete"


@router.get("", response_model=Page[PlaylistSummary])
def list_playlists(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    base = (
        select(Playlist, _KNOWN.label("known"), _DOWNLOADED.label("downloaded"))
        .outerjoin(PlaylistTrack, PlaylistTrack.playlist_id == Playlist.id)  # type: ignore[arg-type]
        .outerjoin(Track, Track.id == PlaylistTrack.track_id)  # type: ignore[arg-type]
        .group_by(Playlist.id)
    )
    with Session(engine) as session:
        total = session.exec(select(func.count()).select_from(base.subquery())).one()
        rows = session.exec(
            base.order_by(Playlist.created_at.desc()).limit(limit).offset(offset)  # type: ignore[attr-defined]
        ).all()
        items = [
            PlaylistSummary(
                id=playlist.id,
                name=playlist.name,
                source=playlist.source,
                total_tracks=known,
                downloaded_tracks=downloaded,
                completeness=_completeness(downloaded, known),
                created_at=playlist.created_at,
            )
            for playlist, known, downloaded in rows
        ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{playlist_id}", response_model=PlaylistDetail)
def playlist_detail(playlist_id: str):
    with Session(engine) as session:
        playlist = session.get(Playlist, playlist_id)
        if playlist is None:
            raise HTTPException(404, "Playlist not found")
        rows = session.exec(
            select(PlaylistTrack, Track)
            .join(Track, Track.id == PlaylistTrack.track_id)  # type: ignore[arg-type]
            .where(PlaylistTrack.playlist_id == playlist_id)
            .order_by(PlaylistTrack.position)
        ).all()
        downloaded = sum(1 for _, track in rows if track.status == TrackStatus.downloaded)
        return PlaylistDetail(
            id=playlist.id,
            name=playlist.name,
            source=playlist.source,
            total_tracks=len(rows),
            downloaded_tracks=downloaded,
            completeness=_completeness(downloaded, len(rows)),
            created_at=playlist.created_at,
            tracks=[
                PlaylistTrackOut(position=pt.position, track=TrackOut(**track.model_dump()))
                for pt, track in rows
            ],
        )


@router.post("/{playlist_id}/complete", response_model=CompletePlaylistResponse)
def complete_playlist(playlist_id: str):
    """Queue a download for every playlist track not yet downloaded
    (Section 7.4 'Complete this playlist' — same pattern as complete_album)."""
    with Session(engine) as session:
        if session.get(Playlist, playlist_id) is None:
            raise HTTPException(404, "Playlist not found")
        missing = session.exec(
            select(Track)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)  # type: ignore[arg-type]
            .where(
                PlaylistTrack.playlist_id == playlist_id,
                Track.status != TrackStatus.downloaded,  # type: ignore[arg-type]
            )
        ).all()
        for track in missing:
            if track.status in (TrackStatus.missing, TrackStatus.error):
                track.status = TrackStatus.queued
                track.error_message = None
                session.add(track)
        session.commit()
        track_ids = [t.id for t in missing]
    queued = 0
    for track_id in track_ids:
        runtime.queue_service.enqueue_download(track_id)
        queued += 1
    return CompletePlaylistResponse(playlist_id=playlist_id, queued_jobs=queued)
