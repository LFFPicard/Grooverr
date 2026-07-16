"""
API request/response schemas. Every endpoint declares a response_model from
here so /docs (OpenAPI) is complete and accurate — a Batch 5 DoD item.
"""
from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from app.resolver.schemas import (
    ResolvedAlbum,
    ResolvedArtist,
    ResolvedPlaylist,
    ResolvedTrack,
)

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Standard pagination envelope (Section 9.2: never the whole library)."""
    items: list[T]
    total: int
    limit: int
    offset: int


# ── Library ────────────────────────────────────────────────────────────────

class TrackOut(BaseModel):
    id: str
    album_id: str
    title: str
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    duration_seconds: Optional[int] = None
    musicbrainz_id: Optional[str] = None
    file_path: Optional[str] = None
    file_format: Optional[str] = None
    bitrate: Optional[str] = None
    status: str
    audio_source: Optional[str] = None
    audio_source_url: Optional[str] = None
    error_message: Optional[str] = None
    has_artwork: Optional[bool] = None
    downloaded_at: Optional[datetime] = None


class AlbumSummary(BaseModel):
    """Library-grid card data (Section 9.2: summary only, no track lists)."""
    id: str
    title: str
    artist_id: str
    artist_name: str
    release_year: Optional[int] = None
    album_type: str
    cover_art_url: Optional[str] = None
    total_tracks: Optional[int] = None       # expected, from metadata source
    downloaded_tracks: int = 0
    known_tracks: int = 0                    # track rows that exist locally
    completeness: str                        # complete | incomplete | empty


class AlbumDetail(AlbumSummary):
    musicbrainz_id: Optional[str] = None
    genre: Optional[str] = None
    created_at: datetime
    tracks: list[TrackOut] = []


class ArtistOut(BaseModel):
    id: str
    name: str
    sort_name: Optional[str] = None
    musicbrainz_id: Optional[str] = None
    album_count: int = 0


# ── Artist Detail (Section 7.1.1) ───────────────────────────────────────────

class ArtistDiscographyItem(BaseModel):
    """One release-group from the artist's MusicBrainz-browsed catalog. The
    embedded `album` is a ResolvedAlbum ready to hand straight to POST
    /api/library/add (type=album) unchanged — its musicbrainz_id is already
    the release-group's own canonical member release."""
    release_group_id: str
    album: ResolvedAlbum
    in_library: bool = False


class DiscographyAddAllResponse(BaseModel):
    """Bulk 'Add entire discography' result — a one-time snapshot, not a
    standing monitor (Section 3 non-goals, clarified 2026-07-14).

    **Post-audit (Section 11 item 15, 2026-07-15):** this now returns
    immediately after enqueueing one album_add job per not-already-owned
    release — jobs_enqueued is a count of *queued* work, not completed
    work. Actual per-release success/failure surfaces through the Queue UI
    (Section 7.5) as each job finishes, same as any other batch of adds."""
    artist_id: str
    release_groups_found: int = 0
    jobs_enqueued: int = 0
    already_in_library: int = 0


# ── Search / add ───────────────────────────────────────────────────────────

class SearchResponse(BaseModel):
    query: str
    query_type: str                          # "url" | "text"
    url_type: Optional[str] = None           # track|album|artist|playlist when url
    mode: str = "all"                        # "all" | "title" | "album" | "artist"
    tracks: list[ResolvedTrack] = []
    albums: list[ResolvedAlbum] = []
    artists: list[ResolvedArtist] = []
    playlist: Optional[ResolvedPlaylist] = None


class AddToLibraryRequest(BaseModel):
    type: str = Field(pattern="^(track|album|artist|playlist)$")
    track: Optional[ResolvedTrack] = None
    album: Optional[ResolvedAlbum] = None
    artist: Optional[ResolvedArtist] = None
    playlist: Optional[ResolvedPlaylist] = None
    quality_kbps: Optional[int] = Field(default=None, ge=32, le=320)
    output_format: Optional[str] = None


class AddToLibraryResponse(BaseModel):
    added_track_ids: list[str] = []
    added_album_id: Optional[str] = None
    added_artist_id: Optional[str] = None
    added_playlist_id: Optional[str] = None
    queued_jobs: int = 0
    already_in_library: int = 0


class QueueTrackActionResponse(BaseModel):
    track_id: str
    job_id: str


class CompleteAlbumResponse(BaseModel):
    album_id: str
    queued_jobs: int


# ── Removal & cleanup (Section 7.6) ─────────────────────────────────────────

class DeleteResponse(BaseModel):
    id: str
    deleted: bool = True
    files_deleted: bool = False
    cascaded_tracks: int = 0
    cascaded_albums: int = 0
    affected_playlists: int = 0


# ── Playlists (Section 5 Playlist/PlaylistTrack, Section 7.4) ──────────────

class PlaylistSummary(BaseModel):
    id: str
    name: str
    source: str
    total_tracks: int = 0
    downloaded_tracks: int = 0
    completeness: str
    m3u_path: Optional[str] = None
    m3u_generated_at: Optional[datetime] = None
    created_at: datetime


class PlaylistTrackOut(BaseModel):
    position: int
    track: TrackOut


class PlaylistDetail(PlaylistSummary):
    tracks: list[PlaylistTrackOut] = []


class CompletePlaylistResponse(BaseModel):
    playlist_id: str
    queued_jobs: int


# ── Queue ──────────────────────────────────────────────────────────────────

class QueueItemOut(BaseModel):
    id: str
    track_id: Optional[str] = None
    job_type: str
    status: str
    progress_percent: int
    priority: int
    requested_quality: Optional[str] = None
    requested_format: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    track_title: Optional[str] = None
    track_status: Optional[str] = None
    artist_name: Optional[str] = None
    album_title: Optional[str] = None


# ── Activity feed ────────────────────────────────────────────────────────

class ActivityItemOut(BaseModel):
    """One finished/errored queue job, newest first (Dashboard 'Recent
    Activity' panel). Not a paginated list — always just the latest N."""
    id: str
    job_type: str
    status: str
    track_title: Optional[str] = None
    artist_name: Optional[str] = None
    album_title: Optional[str] = None
    error_message: Optional[str] = None
    occurred_at: datetime


class ActivityFeedOut(BaseModel):
    items: list[ActivityItemOut]


# ── Stats / settings ───────────────────────────────────────────────────────

class StatsOut(BaseModel):
    """Dashboard stat row — produced by one aggregate query (Section 9.5)."""
    downloading: int
    queued: int
    library_tracks: int
    library_albums: int
    incomplete_albums: int
    errored_jobs: int


# ── Version (Section 8 Settings footer, Batch 9, Section 11 item 19) ───────

class VersionOut(BaseModel):
    """Baked into the image at Docker build time — never computed at
    runtime, which would show the same value regardless of what commit is
    actually running. Local dev (no baked file) falls back to a clearly
    labeled placeholder rather than pretending to be a real build."""
    git_sha: str
    build_date: Optional[str] = None
