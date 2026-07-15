"""
Library endpoints (Sections 7.4 / 9.2).

The album grid is a single aggregated query (join + GROUP BY, no N+1):
summary data only — the track list lives behind the separate, cheap album
detail endpoint. Everything is paginated with server-side filtering.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, or_
from sqlmodel import Session, select

from app.api.schemas import (
    AddToLibraryRequest,
    AddToLibraryResponse,
    AlbumDetail,
    AlbumSummary,
    ArtistOut,
    CompleteAlbumResponse,
    Page,
    QueueTrackActionResponse,
    TrackOut,
)
from app.db import engine
from app.downloader.m3u import regenerate_playlist_m3u
from app.downloader.ytdlp import SUPPORTED_FORMATS
from app.models import Album, Artist, Playlist, PlaylistTrack, Track, TrackStatus
from app.resolver.musicbrainz import _release_rank
from app.resolver.schemas import ResolvedAlbum, ResolvedTrack
from app import runtime

router = APIRouter(prefix="/api/library", tags=["library"])

_DOWNLOADED = func.coalesce(
    func.sum(case((Track.status == TrackStatus.downloaded, 1), else_=0)), 0
)
_KNOWN = func.count(Track.id)
# Expected track count: the metadata source's number, else what we know of.
_EXPECTED = func.coalesce(Album.total_tracks, _KNOWN)

_SORTS = {
    "title": lambda: (Album.title,),
    "artist": lambda: (Artist.name, Album.title),
    "year": lambda: (Album.release_year, Album.title),
    "added": lambda: (Album.created_at.desc(),),  # type: ignore[attr-defined]
}


def _completeness(downloaded: int, expected: int) -> str:
    if downloaded <= 0:
        return "empty"
    return "complete" if downloaded >= expected else "incomplete"


def _album_grid_query(
    artist_id: Optional[str],
    completeness: Optional[str],
    file_format: Optional[str],
    search: Optional[str],
):
    query = (
        select(Album, Artist.name, _DOWNLOADED.label("downloaded"), _KNOWN.label("known"))
        .join(Artist, Artist.id == Album.artist_id)  # type: ignore[arg-type]
        .outerjoin(Track, Track.album_id == Album.id)  # type: ignore[arg-type]
        .group_by(Album.id)
    )
    if artist_id:
        query = query.where(Album.artist_id == artist_id)
    if search:
        term = f"%{search}%"
        query = query.where(or_(Album.title.like(term), Artist.name.like(term)))  # type: ignore[attr-defined]
    if file_format:
        query = query.having(
            func.sum(case((Track.file_format == file_format, 1), else_=0)) > 0
        )
    if completeness == "complete":
        query = query.having(_DOWNLOADED >= _EXPECTED).having(_DOWNLOADED > 0)
    elif completeness == "incomplete":
        query = query.having(_DOWNLOADED > 0).having(_DOWNLOADED < _EXPECTED)
    elif completeness == "empty":
        query = query.having(_DOWNLOADED == 0)
    return query


@router.get("/albums", response_model=Page[AlbumSummary])
def list_albums(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    artist_id: Optional[str] = None,
    completeness: Optional[str] = Query(default=None, pattern="^(complete|incomplete|empty)$"),
    file_format: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = Query(default="title", pattern="^(title|artist|year|added)$"),
):
    base = _album_grid_query(artist_id, completeness, file_format, search)
    with Session(engine) as session:
        total = session.exec(
            select(func.count()).select_from(base.subquery())
        ).one()
        rows = session.exec(
            base.order_by(*_SORTS[sort]()).limit(limit).offset(offset)
        ).all()
        items = []
        for album, artist_name, downloaded, known in rows:
            expected = album.total_tracks or known
            items.append(
                AlbumSummary(
                    id=album.id,
                    title=album.title,
                    artist_id=album.artist_id,
                    artist_name=artist_name,
                    release_year=album.release_year,
                    album_type=album.album_type.value,
                    cover_art_url=album.cover_art_url,
                    total_tracks=album.total_tracks,
                    downloaded_tracks=downloaded,
                    known_tracks=known,
                    completeness=_completeness(downloaded, expected),
                )
            )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/albums/{album_id}", response_model=AlbumDetail)
def album_detail(album_id: str):
    """Cheap single-album endpoint (Section 9.2): one album row + its
    tracks — two indexed queries, no aggregation over the library."""
    with Session(engine) as session:
        album = session.get(Album, album_id)
        if album is None:
            raise HTTPException(404, "Album not found")
        artist = session.get(Artist, album.artist_id)
        tracks = session.exec(
            select(Track)
            .where(Track.album_id == album_id)
            .order_by(Track.disc_number, Track.track_number, Track.created_at)
        ).all()
        downloaded = sum(1 for t in tracks if t.status == TrackStatus.downloaded)
        expected = album.total_tracks or len(tracks)
        return AlbumDetail(
            id=album.id,
            title=album.title,
            artist_id=album.artist_id,
            artist_name=artist.name if artist else "Unknown Artist",
            release_year=album.release_year,
            album_type=album.album_type.value,
            cover_art_url=album.cover_art_url,
            total_tracks=album.total_tracks,
            downloaded_tracks=downloaded,
            known_tracks=len(tracks),
            completeness=_completeness(downloaded, expected),
            musicbrainz_id=album.musicbrainz_id,
            genre=album.genre,
            created_at=album.created_at,
            tracks=[TrackOut(**t.model_dump()) for t in tracks],
        )


@router.get("/artists", response_model=Page[ArtistOut])
def list_artists(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = None,
):
    base = (
        select(Artist, func.count(Album.id).label("albums"))
        .outerjoin(Album, Album.artist_id == Artist.id)  # type: ignore[arg-type]
        .group_by(Artist.id)
    )
    if search:
        base = base.where(Artist.name.like(f"%{search}%"))  # type: ignore[attr-defined]
    with Session(engine) as session:
        total = session.exec(select(func.count()).select_from(base.subquery())).one()
        rows = session.exec(base.order_by(Artist.name).limit(limit).offset(offset)).all()
        items = [
            ArtistOut(
                id=artist.id,
                name=artist.name,
                sort_name=artist.sort_name,
                musicbrainz_id=artist.musicbrainz_id,
                album_count=count,
            )
            for artist, count in rows
        ]
    return Page(items=items, total=total, limit=limit, offset=offset)


# ── Add to library (Section 7.1 step 5) ────────────────────────────────────

def _find_or_create_artist(session: Session, name: Optional[str],
                           mbid: Optional[str] = None) -> Artist:
    # Resolve the effective name before searching, so two tracks with no
    # artist metadata at all dedupe onto the same "Unknown Artist" row
    # instead of each minting a fresh one.
    effective_name = name or "Unknown Artist"
    artist = None
    if mbid:
        artist = session.exec(select(Artist).where(Artist.musicbrainz_id == mbid)).first()
    if artist is None:
        artist = session.exec(select(Artist).where(Artist.name == effective_name)).first()
    if artist is None:
        artist = Artist(name=effective_name, musicbrainz_id=mbid)
        session.add(artist)
        session.flush()
    return artist


def _find_or_create_album(session: Session, artist: Artist, resolved: ResolvedAlbum) -> Album:
    # Same reasoning as _find_or_create_artist: search on the effective
    # title so albums with no metadata dedupe onto one "Unknown Album" row.
    effective_title = resolved.title or "Unknown Album"
    album = None
    if resolved.musicbrainz_id:
        album = session.exec(
            select(Album).where(Album.musicbrainz_id == resolved.musicbrainz_id)
        ).first()
    if album is None:
        album = session.exec(
            select(Album).where(Album.artist_id == artist.id, Album.title == effective_title)
        ).first()
    if album is None:
        album = Album(
            artist_id=artist.id,
            title=effective_title,
            musicbrainz_id=resolved.musicbrainz_id,
            release_year=resolved.release_year,
            album_type=resolved.album_type or "album",
            total_tracks=resolved.total_tracks,
            cover_art_url=resolved.cover_art_url,
            genre=resolved.genre,
        )
        session.add(album)
        session.flush()
    return album


def _create_track(session: Session, album: Album, resolved: ResolvedTrack) -> Optional[Track]:
    """Create a Track row from resolved metadata; None if already present."""
    if resolved.musicbrainz_id:
        existing = session.exec(
            select(Track).where(Track.musicbrainz_id == resolved.musicbrainz_id)
        ).first()
        if existing is not None:
            return None
    existing = session.exec(
        select(Track).where(Track.album_id == album.id, Track.title == resolved.title)
    ).first()
    if existing is not None:
        return None
    track = Track(
        album_id=album.id,
        title=resolved.title,
        track_number=resolved.track_number,
        disc_number=resolved.disc_number,
        duration_seconds=resolved.duration_seconds,
        musicbrainz_id=resolved.musicbrainz_id,
        status=TrackStatus.queued,
        youtube_video_id=resolved.youtube_video_id,
        audio_source_url=(
            f"https://music.youtube.com/watch?v={resolved.youtube_video_id}"
            if resolved.youtube_video_id else None
        ),
    )
    session.add(track)
    session.flush()
    return track


async def _resolve_full_album(resolved_album: ResolvedAlbum) -> ResolvedAlbum:
    """Fills in the track list for a summary-only ResolvedAlbum (search
    results and Artist Detail discography hits both carry no track list) via
    a single get_release/get_album lookup — shared by the single-album add
    path and the Artist Detail bulk "add entire discography" path."""
    if resolved_album.tracks:
        return resolved_album
    full = None
    if resolved_album.musicbrainz_id:
        release = await runtime.resolver.mb.get_release(resolved_album.musicbrainz_id)
        full = runtime.resolver.mb.parse_release(release)
    elif resolved_album.release_group_id:
        # Artist Detail discography items (Section 7.1.1) carry a
        # release-group id, not a release id — the canonical member release
        # is picked here, lazily, only when the user actually adds it (see
        # browse_release_groups_by_artist's docstring for why this can't
        # happen eagerly at browse time).
        releases = await runtime.resolver.mb.browse_releases_by_release_group(
            resolved_album.release_group_id
        )
        # Safe .get() only — a release entry with no id (malformed payload)
        # must fall through to the 502 below, not raise a raw KeyError
        # (Batch 2 hard rule; a KeyError here would also abort an entire
        # bulk add-all run, since that loop only catches HTTPException).
        candidates = [r for r in releases if r.get("id")]
        if candidates:
            best = max(candidates, key=_release_rank)
            release = await runtime.resolver.mb.get_release(best["id"])
            full = runtime.resolver.mb.parse_release(release)
    elif resolved_album.youtube_browse_id or resolved_album.youtube_playlist_id:
        full = await asyncio.to_thread(
            runtime.resolver.yt.get_album,
            resolved_album.youtube_browse_id or resolved_album.youtube_playlist_id,
        )
    if full is None or not full.tracks:
        raise HTTPException(502, "Could not resolve the album's track list")
    full.cover_art_url = full.cover_art_url or resolved_album.cover_art_url
    return full


def _persist_album(session: Session, resolved_album: ResolvedAlbum) -> tuple[Album, list[str], int]:
    """Dedup artist/album/tracks and persist — does not commit or enqueue."""
    artist = _find_or_create_artist(
        session, resolved_album.artist_name, resolved_album.musicbrainz_artist_id
    )
    album = _find_or_create_album(session, artist, resolved_album)
    new_track_ids = []
    already_in_library = 0
    for resolved_track in resolved_album.tracks:
        track = _create_track(session, album, resolved_track)
        if track is None:
            already_in_library += 1
        else:
            new_track_ids.append(track.id)
    return album, new_track_ids, already_in_library


async def _add_album(
    resolved_album: ResolvedAlbum,
    quality: Optional[str] = None,
    output_format: Optional[str] = None,
) -> AddToLibraryResponse:
    """The full "add an album" operation: resolve → dedup/persist → enqueue
    downloads. Shared by POST /add (type=album) and Artist Detail's bulk
    add-all (Section 7.1.1), so both go through identical, once-tested logic."""
    resolved_album = await _resolve_full_album(resolved_album)
    with Session(engine) as session:
        album, new_track_ids, already_in_library = _persist_album(session, resolved_album)
        session.commit()
        album_id = album.id
    for track_id in new_track_ids:
        runtime.queue_service.enqueue_download(track_id, quality=quality, output_format=output_format)
    return AddToLibraryResponse(
        added_album_id=album_id,
        added_track_ids=new_track_ids,
        queued_jobs=len(new_track_ids),
        already_in_library=already_in_library,
    )


@router.post("/add", response_model=AddToLibraryResponse, status_code=202)
async def add_to_library(body: AddToLibraryRequest):
    if body.output_format and body.output_format not in SUPPORTED_FORMATS:
        raise HTTPException(
            422,
            f"Unsupported format {body.output_format!r} — supported: {', '.join(SUPPORTED_FORMATS)}",
        )
    quality = str(body.quality_kbps) if body.quality_kbps else None
    response = AddToLibraryResponse()

    if body.type == "track":
        if body.track is None:
            raise HTTPException(422, "type=track requires a 'track' object")
        with Session(engine) as session:
            artist = _find_or_create_artist(
                session, body.track.album_artist or body.track.artist_name,
                body.track.musicbrainz_artist_id,
            )
            album = _find_or_create_album(
                session, artist,
                ResolvedAlbum(
                    title=body.track.album_title or "Unknown Album",
                    musicbrainz_id=body.track.musicbrainz_release_id,
                    release_year=body.track.release_year,
                    cover_art_url=body.track.cover_art_url,
                    genre=body.track.genre,
                    source=body.track.source,
                ),
            )
            track = _create_track(session, album, body.track)
            if track is None:
                response.already_in_library = 1
                session.commit()
                return response
            session.commit()
            response.added_track_ids = [track.id]
            response.added_album_id = album.id
        # Metadata already resolved (came from a search result) → straight
        # to download; resolve first when the payload has no source ids.
        if body.track.musicbrainz_id or body.track.youtube_video_id:
            runtime.queue_service.enqueue_download(
                response.added_track_ids[0], quality=quality, output_format=body.output_format
            )
        else:
            runtime.queue_service.enqueue_resolve(
                response.added_track_ids[0], quality=quality, output_format=body.output_format
            )
        response.queued_jobs = 1
        return response

    if body.type == "album":
        if body.album is None:
            raise HTTPException(422, "type=album requires an 'album' object")
        # Search summaries carry no track list — _add_album resolves it in
        # one pass (Section 7.1 step 5: per-album resolution where supported).
        return await _add_album(body.album, quality=quality, output_format=body.output_format)

    if body.type == "artist":
        if body.artist is None:
            raise HTTPException(422, "type=artist requires an 'artist' object")
        with Session(engine) as session:
            artist = _find_or_create_artist(
                session, body.artist.name, body.artist.musicbrainz_id
            )
            session.commit()
            response.added_artist_id = artist.id
        return response

    # playlist: create/reuse a Playlist row and link each track into it via
    # PlaylistTrack (Section 5) — this is what "Complete this playlist"
    # (Section 7.4) groups against. Each track goes through the same
    # album/artist dedup as a standalone add, since playlist tracks usually
    # span many different artists/albums.
    if body.playlist is None:
        raise HTTPException(422, "type=playlist requires a 'playlist' object")
    resolved_playlist = body.playlist

    with Session(engine) as session:
        playlist = None
        if resolved_playlist.youtube_playlist_id:
            playlist = session.exec(
                select(Playlist).where(
                    Playlist.source_playlist_id == resolved_playlist.youtube_playlist_id
                )
            ).first()
        if playlist is None:
            playlist = Playlist(
                name=resolved_playlist.title or "Untitled Playlist",
                source="youtube-music",
                source_playlist_id=resolved_playlist.youtube_playlist_id,
            )
            session.add(playlist)
            session.flush()

        new_tracks = []
        for position, resolved_track in enumerate(resolved_playlist.tracks, start=1):
            artist = _find_or_create_artist(
                session, resolved_track.album_artist or resolved_track.artist_name,
                resolved_track.musicbrainz_artist_id,
            )
            album = _find_or_create_album(
                session, artist,
                ResolvedAlbum(
                    title=resolved_track.album_title or "Unknown Album",
                    musicbrainz_id=resolved_track.musicbrainz_release_id,
                    release_year=resolved_track.release_year,
                    cover_art_url=resolved_track.cover_art_url,
                    genre=resolved_track.genre,
                    source=resolved_track.source,
                ),
            )
            track = _create_track(session, album, resolved_track)
            if track is None:
                response.already_in_library += 1
                track = session.exec(
                    select(Track).where(
                        Track.album_id == album.id, Track.title == resolved_track.title
                    )
                ).first()
            else:
                new_tracks.append((track.id, resolved_track))

            if track is not None:
                already_linked = session.exec(
                    select(PlaylistTrack).where(
                        PlaylistTrack.playlist_id == playlist.id,
                        PlaylistTrack.track_id == track.id,
                    )
                ).first()
                if already_linked is None:
                    session.add(
                        PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=position)
                    )

        session.commit()
        response.added_playlist_id = playlist.id
        response.added_track_ids = [track_id for track_id, _ in new_tracks]

        # Section 6.1: write the initial manifest right away (likely empty
        # or partial until downloads complete) so the file exists as soon
        # as the playlist does.
        regenerate_playlist_m3u(session, playlist)

    for track_id, resolved_track in new_tracks:
        # Same rule as a standalone track add: skip straight to download
        # when the source already gave us an id to work with, else resolve
        # first for canonical MusicBrainz metadata.
        if resolved_track.musicbrainz_id or resolved_track.youtube_video_id:
            runtime.queue_service.enqueue_download(
                track_id, quality=quality, output_format=body.output_format
            )
        else:
            runtime.queue_service.enqueue_resolve(
                track_id, quality=quality, output_format=body.output_format
            )
    response.queued_jobs = len(response.added_track_ids)
    return response


# ── Album / track actions (Section 7.4) ────────────────────────────────────

@router.post("/albums/{album_id}/complete", response_model=CompleteAlbumResponse)
def complete_album(album_id: str):
    """Queue a download for every known track of the album that isn't
    downloaded yet (Section 7.4 'Complete this album')."""
    with Session(engine) as session:
        if session.get(Album, album_id) is None:
            raise HTTPException(404, "Album not found")
        missing = session.exec(
            select(Track).where(
                Track.album_id == album_id,
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
    return CompleteAlbumResponse(album_id=album_id, queued_jobs=queued)


@router.post("/tracks/{track_id}/download", response_model=QueueTrackActionResponse, status_code=202)
def download_track(track_id: str):
    """Per-track 'download this one' action (album detail view)."""
    with Session(engine) as session:
        track = session.get(Track, track_id)
        if track is None:
            raise HTTPException(404, "Track not found")
        if track.status == TrackStatus.downloading:
            raise HTTPException(409, "Track is already downloading")
        track.status = TrackStatus.queued
        track.error_message = None
        session.add(track)
        session.commit()
    job_id = runtime.queue_service.enqueue_download(track_id)
    return QueueTrackActionResponse(track_id=track_id, job_id=job_id)
