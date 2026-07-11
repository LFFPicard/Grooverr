"""
Resolved-metadata schemas returned by the resolution engine.

These are transport objects between the resolver and the rest of the app
(queue workers, API layer). Field names mirror the Section 5 data model so
persisting a resolved result onto Artist/Album/Track rows is a direct mapping.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class MetadataSource(str, Enum):
    musicbrainz = "musicbrainz"
    youtube_music = "youtube-music"


class ResolvedArtist(BaseModel):
    name: str
    sort_name: Optional[str] = None
    musicbrainz_id: Optional[str] = None
    youtube_channel_id: Optional[str] = None
    source: MetadataSource


class ResolvedTrack(BaseModel):
    title: str
    artist_name: Optional[str] = None
    album_title: Optional[str] = None
    track_number: Optional[int] = None
    disc_number: Optional[int] = None
    duration_seconds: Optional[int] = None
    release_year: Optional[int] = None
    genre: Optional[str] = None
    musicbrainz_id: Optional[str] = None          # recording MBID
    musicbrainz_release_id: Optional[str] = None
    musicbrainz_artist_id: Optional[str] = None
    youtube_video_id: Optional[str] = None
    cover_art_url: Optional[str] = None
    source: MetadataSource


class ResolvedAlbum(BaseModel):
    title: str
    artist_name: Optional[str] = None
    album_type: Optional[str] = None              # album | single | compilation | ep
    release_year: Optional[int] = None
    total_tracks: Optional[int] = None
    genre: Optional[str] = None
    musicbrainz_id: Optional[str] = None          # release MBID
    musicbrainz_artist_id: Optional[str] = None
    youtube_browse_id: Optional[str] = None
    youtube_playlist_id: Optional[str] = None
    cover_art_url: Optional[str] = None
    tracks: list[ResolvedTrack] = []
    source: MetadataSource


class ResolvedPlaylist(BaseModel):
    title: str
    author: Optional[str] = None
    youtube_playlist_id: Optional[str] = None
    total_tracks: Optional[int] = None
    tracks: list[ResolvedTrack] = []
    source: MetadataSource
