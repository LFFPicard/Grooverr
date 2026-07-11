"""
YouTube Music client wrapper (ytmusicapi) — search + URL resolution.
No downloading here (that's Batch 3); this is metadata only.

ytmusicapi is synchronous; the resolution engine calls these methods via
asyncio.to_thread. All response parsing uses safe .get() access with
defaults — ytmusicapi output is scraped from YT Music's internal API and
its shape shifts without warning (same failure mode as the spotDL-GUI
Spotify client; Batch 2 hard requirement).
"""
from typing import Any, Optional

from ytmusicapi import YTMusic

from app.resolver.schemas import (
    MetadataSource,
    ResolvedArtist,
    ResolvedAlbum,
    ResolvedTrack,
    ResolvedPlaylist,
)


def _parse_duration(value: Any) -> Optional[int]:
    """'3:14' / '1:02:03' / 194 → seconds. None on anything unparseable."""
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if not parts or not all(p.strip().isdigit() for p in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


def _parse_year(value: Any) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def _first_artist_name(item: dict) -> Optional[str]:
    artists = item.get("artists")
    if isinstance(artists, list):
        for artist in artists:
            name = artist.get("name") if isinstance(artist, dict) else None
            if name:
                return str(name)
    author = item.get("author")
    if isinstance(author, str):
        return author
    if isinstance(author, dict):
        name = author.get("name")
        if name:
            return str(name)
    return None


def _largest_thumbnail(item: dict) -> Optional[str]:
    """ytmusicapi thumbnail lists are ordered smallest → largest."""
    for key in ("thumbnails", "thumbnail"):
        thumbs = item.get(key)
        if isinstance(thumbs, list) and thumbs:
            last = thumbs[-1]
            url = last.get("url") if isinstance(last, dict) else None
            if url:
                return str(url)
    return None


def _album_title(item: dict) -> Optional[str]:
    album = item.get("album")
    if isinstance(album, dict):
        return album.get("name")
    if isinstance(album, str):
        return album
    return None


def _parse_track(
    item: dict,
    album_title: Optional[str] = None,
    track_number: Optional[int] = None,
    release_year: Optional[int] = None,
    cover_art_url: Optional[str] = None,
    artist_name: Optional[str] = None,
) -> ResolvedTrack:
    """Common mapper for song-shaped ytmusicapi dicts (search results,
    album tracks, playlist tracks, watch-playlist tracks)."""
    duration = (
        item.get("duration_seconds")
        if isinstance(item.get("duration_seconds"), int)
        else _parse_duration(item.get("duration") or item.get("length"))
    )
    number = item.get("trackNumber")
    if not isinstance(number, int):
        number = track_number
    return ResolvedTrack(
        title=str(item.get("title") or ""),
        artist_name=_first_artist_name(item) or artist_name,
        album_title=_album_title(item) or album_title,
        track_number=number,
        duration_seconds=duration,
        release_year=_parse_year(item.get("year")) or release_year,
        youtube_video_id=item.get("videoId"),
        cover_art_url=_largest_thumbnail(item) or cover_art_url,
        source=MetadataSource.youtube_music,
    )


class YouTubeMusicClient:
    def __init__(self, ytmusic: Optional[YTMusic] = None):
        # Unauthenticated works for all metadata operations used here.
        self._yt = ytmusic or YTMusic()

    # ── Search ────────────────────────────────────────────────────────────

    def search_songs(self, query: str, limit: int = 10) -> list[ResolvedTrack]:
        results = self._yt.search(query, filter="songs", limit=limit)
        results = results if isinstance(results, list) else []
        return [_parse_track(r) for r in results if isinstance(r, dict)]

    def search_videos(self, query: str, limit: int = 10) -> list[ResolvedTrack]:
        """Plain YouTube video search — the last-resort audio-source fallback
        (Section 7.3 step 3) when no YT Music song matches."""
        results = self._yt.search(query, filter="videos", limit=limit)
        results = results if isinstance(results, list) else []
        return [_parse_track(r) for r in results if isinstance(r, dict)]

    def search_albums(self, query: str, limit: int = 10) -> list[ResolvedAlbum]:
        results = self._yt.search(query, filter="albums", limit=limit)
        albums = []
        for item in results if isinstance(results, list) else []:
            if not isinstance(item, dict):
                continue
            albums.append(
                ResolvedAlbum(
                    title=str(item.get("title") or ""),
                    artist_name=_first_artist_name(item),
                    album_type=str(item.get("type") or "").lower() or None,
                    release_year=_parse_year(item.get("year")),
                    youtube_browse_id=item.get("browseId"),
                    youtube_playlist_id=item.get("playlistId"),
                    cover_art_url=_largest_thumbnail(item),
                    source=MetadataSource.youtube_music,
                )
            )
        return albums

    def search_artists(self, query: str, limit: int = 10) -> list[ResolvedArtist]:
        results = self._yt.search(query, filter="artists", limit=limit)
        artists = []
        for item in results if isinstance(results, list) else []:
            if not isinstance(item, dict):
                continue
            artists.append(
                ResolvedArtist(
                    name=str(item.get("artist") or item.get("title") or ""),
                    youtube_channel_id=item.get("browseId"),
                    source=MetadataSource.youtube_music,
                )
            )
        return artists

    # ── URL resolution ────────────────────────────────────────────────────

    def get_track(self, video_id: str) -> Optional[ResolvedTrack]:
        """Resolve a watch URL's video id. get_watch_playlist is used instead
        of get_song because its first entry includes album info."""
        data = self._yt.get_watch_playlist(videoId=video_id, limit=1)
        data = data if isinstance(data, dict) else {}
        tracks = data.get("tracks")
        for item in tracks if isinstance(tracks, list) else []:
            if isinstance(item, dict) and item.get("videoId") == video_id:
                return _parse_track(item)
        # Fall back to the first entry (watch playlists start with the seed video).
        first = tracks[0] if isinstance(tracks, list) and tracks else None
        if isinstance(first, dict):
            return _parse_track(first)
        return None

    def get_album(self, album_id: str) -> Optional[ResolvedAlbum]:
        """Resolve an album from a browse id (MPREb_…) or an audio-playlist
        id (OLAK5uy_…), which is first translated to a browse id."""
        browse_id: Optional[str] = album_id
        if not album_id.startswith("MPREb_"):
            browse_id = self._yt.get_album_browse_id(album_id)
        if not browse_id:
            return None
        data = self._yt.get_album(browse_id)
        data = data if isinstance(data, dict) else {}
        if not data:
            return None

        title = str(data.get("title") or "")
        artist_name = _first_artist_name(data)
        year = _parse_year(data.get("year"))
        cover = _largest_thumbnail(data)
        raw_tracks = data.get("tracks")
        raw_tracks = raw_tracks if isinstance(raw_tracks, list) else []
        tracks = [
            _parse_track(
                item,
                album_title=title,
                track_number=position,
                release_year=year,
                cover_art_url=cover,
                artist_name=artist_name,
            )
            for position, item in enumerate(raw_tracks, start=1)
            if isinstance(item, dict)
        ]
        track_count = data.get("trackCount")
        audio_playlist_id = data.get("audioPlaylistId")
        return ResolvedAlbum(
            title=title,
            artist_name=artist_name,
            album_type=str(data.get("type") or "").lower() or None,
            release_year=year,
            total_tracks=track_count if isinstance(track_count, int) else len(tracks) or None,
            youtube_browse_id=browse_id,
            youtube_playlist_id=audio_playlist_id if isinstance(audio_playlist_id, str) else None,
            cover_art_url=cover,
            tracks=tracks,
            source=MetadataSource.youtube_music,
        )

    def get_artist(self, channel_id: str) -> Optional[ResolvedArtist]:
        data = self._yt.get_artist(channel_id)
        data = data if isinstance(data, dict) else {}
        name = data.get("name")
        if not name:
            return None
        return ResolvedArtist(
            name=str(name),
            youtube_channel_id=data.get("channelId") or channel_id,
            source=MetadataSource.youtube_music,
        )

    def get_playlist(self, playlist_id: str, limit: Optional[int] = None) -> Optional[ResolvedPlaylist]:
        data = self._yt.get_playlist(playlist_id, limit=limit)
        data = data if isinstance(data, dict) else {}
        if not data:
            return None
        raw_tracks = data.get("tracks")
        raw_tracks = raw_tracks if isinstance(raw_tracks, list) else []
        tracks = [_parse_track(item) for item in raw_tracks if isinstance(item, dict)]
        track_count = data.get("trackCount")
        return ResolvedPlaylist(
            title=str(data.get("title") or ""),
            author=_first_artist_name(data),
            youtube_playlist_id=data.get("id") or playlist_id,
            total_tracks=track_count if isinstance(track_count, int) else len(tracks) or None,
            tracks=tracks,
            source=MetadataSource.youtube_music,
        )
