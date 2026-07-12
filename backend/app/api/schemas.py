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


# ── Search / add ───────────────────────────────────────────────────────────

class SearchResponse(BaseModel):
    query: str
    query_type: str                          # "url" | "text"
    url_type: Optional[str] = None           # track|album|artist|playlist when url
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
    queued_jobs: int = 0
    already_in_library: int = 0


class QueueTrackActionResponse(BaseModel):
    track_id: str
    job_id: str


class CompleteAlbumResponse(BaseModel):
    album_id: str
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


# ── Stats / settings ───────────────────────────────────────────────────────

class StatsOut(BaseModel):
    """Dashboard stat row — produced by one aggregate query (Section 9.5)."""
    downloading: int
    queued: int
    library_tracks: int
    library_albums: int
    incomplete_albums: int
    errored_jobs: int
