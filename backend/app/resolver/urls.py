"""
YouTube / YouTube Music URL detection (Section 7.1 step 2).

Given a pasted URL, classify it as track / album / artist / playlist and
extract the identifier needed to resolve it via ytmusicapi.

YouTube Music URL shapes handled:
  track:    music.youtube.com/watch?v=<videoId>[&list=...]
  album:    music.youtube.com/playlist?list=OLAK5uy_<...>   (audio playlist)
            music.youtube.com/browse/MPREb_<...>            (album browse id)
  artist:   music.youtube.com/channel/<channelId>
  playlist: music.youtube.com/playlist?list=<anything else>
Plain YouTube (youtube.com/watch, youtu.be/<id>) is treated as a track.
"""
from enum import Enum
from typing import Optional
from urllib.parse import urlparse, parse_qs

from pydantic import BaseModel

_YOUTUBE_HOSTS = {
    "music.youtube.com",
    "www.youtube.com",
    "youtube.com",
    "m.youtube.com",
}
ALBUM_PLAYLIST_PREFIX = "OLAK5uy_"   # YT Music album ("audio") playlists
ALBUM_BROWSE_PREFIX = "MPREb_"


class UrlType(str, Enum):
    track = "track"
    album = "album"
    artist = "artist"
    playlist = "playlist"


class ParsedUrl(BaseModel):
    url_type: UrlType
    id: str                      # videoId / playlistId / browseId / channelId
    is_music_domain: bool = True


def parse_music_url(url: str) -> Optional[ParsedUrl]:
    """Classify a YouTube / YouTube Music URL. Returns None if unrecognised."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")
    is_music = host == "music.youtube.com"

    if host == "youtu.be":
        video_id = path.lstrip("/").split("/")[0]
        if video_id:
            return ParsedUrl(url_type=UrlType.track, id=video_id, is_music_domain=False)
        return None

    if host not in _YOUTUBE_HOSTS:
        return None

    if path == "/watch":
        video_id = (query.get("v") or [""])[0]
        if video_id:
            return ParsedUrl(url_type=UrlType.track, id=video_id, is_music_domain=is_music)
        return None

    if path == "/playlist":
        playlist_id = (query.get("list") or [""])[0]
        if not playlist_id:
            return None
        # ytmusicapi accepts ids with or without the "VL" prefix; normalise it off.
        if playlist_id.startswith("VL"):
            playlist_id = playlist_id[2:]
        if playlist_id.startswith(ALBUM_PLAYLIST_PREFIX):
            return ParsedUrl(url_type=UrlType.album, id=playlist_id, is_music_domain=is_music)
        return ParsedUrl(url_type=UrlType.playlist, id=playlist_id, is_music_domain=is_music)

    segments = [s for s in path.split("/") if s]
    if len(segments) == 2:
        kind, identifier = segments[0], segments[1]
        if kind == "browse" and identifier.startswith(ALBUM_BROWSE_PREFIX):
            return ParsedUrl(url_type=UrlType.album, id=identifier, is_music_domain=is_music)
        if kind == "channel":
            return ParsedUrl(url_type=UrlType.artist, id=identifier, is_music_domain=is_music)

    return None
