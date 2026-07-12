"""
Data models — matches Section 5 of grooverr.md exactly.
Indexes noted in the spec are applied via `index=True` / composite Index() below.
"""
import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlmodel import SQLModel, Field, Index


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Enums ──────────────────────────────────────────────────────────────────

class AlbumType(str, Enum):
    album = "album"
    single = "single"
    compilation = "compilation"
    ep = "ep"


class TrackStatus(str, Enum):
    missing = "missing"
    queued = "queued"
    downloading = "downloading"
    downloaded = "downloaded"
    error = "error"


class AudioSource(str, Enum):
    youtube_music = "youtube-music"
    youtube = "youtube"


class JobType(str, Enum):
    metadata_resolve = "metadata_resolve"
    download = "download"


class JobStatus(str, Enum):
    queued = "queued"
    active = "active"
    done = "done"
    error = "error"


# ── Core entities ─────────────────────────────────────────────────────────

class Artist(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str
    sort_name: Optional[str] = None
    musicbrainz_id: Optional[str] = Field(default=None, index=True)
    spotify_id: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Album(SQLModel, table=True):
    __table_args__ = (
        Index("ix_album_artist_title", "artist_id", "title"),
    )

    id: str = Field(default_factory=_uuid, primary_key=True)
    artist_id: str = Field(foreign_key="artist.id", index=True)
    title: str
    musicbrainz_id: Optional[str] = Field(default=None, index=True)
    spotify_id: Optional[str] = Field(default=None, index=True)
    release_year: Optional[int] = None
    album_type: AlbumType = Field(default=AlbumType.album)
    total_tracks: Optional[int] = None
    cover_art_url: Optional[str] = None
    # Extension over the Section 5 field list (flagged in Section 11): genre
    # from the metadata source, needed at tagging time (Section 6 tag set).
    genre: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Track(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    album_id: str = Field(foreign_key="album.id", index=True)
    title: str
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    duration_seconds: Optional[int] = None
    musicbrainz_id: Optional[str] = Field(default=None, index=True)
    spotify_id: Optional[str] = Field(default=None, index=True)
    file_path: Optional[str] = None
    file_format: Optional[str] = None
    bitrate: Optional[str] = None
    status: TrackStatus = Field(default=TrackStatus.missing, index=True)
    audio_source: Optional[AudioSource] = None
    audio_source_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    downloaded_at: Optional[datetime] = None


class QueueItem(SQLModel, table=True):
    id: str = Field(default_factory=_uuid, primary_key=True)
    track_id: Optional[str] = Field(default=None, foreign_key="track.id", index=True)
    job_type: JobType = Field(index=True)
    status: JobStatus = Field(default=JobStatus.queued, index=True)
    progress_percent: int = Field(default=0)
    priority: int = Field(default=100)
    requested_quality: Optional[str] = None      # bitrate ceiling in kbps
    # Extension over the Section 5 field list (flagged in Section 11): the
    # per-download output format travels with the job like the quality does.
    requested_format: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None


class Settings(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str  # JSON-encoded
