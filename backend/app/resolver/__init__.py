"""
Metadata resolution engine (Batch 2, grooverr.md Section 10).

Resolves tracks/albums/artists/playlists to canonical metadata:
MusicBrainz primary, YouTube Music fallback (Section 7.2).
"""
from app.resolver.schemas import (
    MetadataSource,
    ResolvedArtist,
    ResolvedAlbum,
    ResolvedTrack,
    ResolvedPlaylist,
)
from app.resolver.urls import UrlType, ParsedUrl, parse_music_url
from app.resolver.musicbrainz import MusicBrainzClient
from app.resolver.ytmusic import YouTubeMusicClient
from app.resolver.engine import MetadataResolver

__all__ = [
    "MetadataSource",
    "ResolvedArtist",
    "ResolvedAlbum",
    "ResolvedTrack",
    "ResolvedPlaylist",
    "UrlType",
    "ParsedUrl",
    "parse_music_url",
    "MusicBrainzClient",
    "YouTubeMusicClient",
    "MetadataResolver",
]
