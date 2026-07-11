"""
Metadata resolution engine — the Section 7.2 fallback chain.

Order of precedence: MusicBrainz (canonical) → YouTube Music (fallback).
A MusicBrainz search hit only counts as confident when its Lucene score
meets `min_score` (MB scores hits 0-100); anything below falls through to
YouTube Music rather than tagging the library with a wrong guess.

ytmusicapi is synchronous, so its calls are pushed to a worker thread via
asyncio.to_thread to keep the event loop free (Section 9.3 workers run in
the FastAPI process).
"""
import asyncio
import logging
from typing import Optional, Union

from app.resolver.musicbrainz import MusicBrainzClient
from app.resolver.ytmusic import YouTubeMusicClient
from app.resolver.urls import UrlType, parse_music_url
from app.resolver.schemas import (
    ResolvedArtist,
    ResolvedAlbum,
    ResolvedTrack,
    ResolvedPlaylist,
)

logger = logging.getLogger("grooverr.resolver")

DEFAULT_MIN_SCORE = 85

ResolvedUrl = Union[ResolvedTrack, ResolvedAlbum, ResolvedArtist, ResolvedPlaylist]


def _score(hit: dict) -> int:
    """MB search score, tolerant of int or numeric-string encodings."""
    score = hit.get("score")
    if isinstance(score, int):
        return score
    if isinstance(score, str) and score.isdigit():
        return int(score)
    return 0


class MetadataResolver:
    def __init__(
        self,
        musicbrainz: Optional[MusicBrainzClient] = None,
        ytmusic: Optional[YouTubeMusicClient] = None,
        min_score: int = DEFAULT_MIN_SCORE,
    ):
        self.mb = musicbrainz or MusicBrainzClient()
        self.yt = ytmusic or YouTubeMusicClient()
        self.min_score = min_score

    async def close(self):
        await self.mb.close()

    # ── Free-text resolution (MusicBrainz → YouTube Music) ────────────────

    async def resolve_track(
        self,
        title: str,
        artist: Optional[str] = None,
        album: Optional[str] = None,
    ) -> Optional[ResolvedTrack]:
        try:
            hits = await self.mb.search_recordings(title, artist=artist, album=album)
        except Exception:
            logger.exception("MusicBrainz recording search failed for %r", title)
            hits = []
        for hit in hits:
            if isinstance(hit, dict) and _score(hit) >= self.min_score:
                return self.mb.parse_recording_hit(hit, album_hint=album)

        logger.info("No confident MusicBrainz match for track %r — trying YouTube Music", title)
        query = " ".join(part for part in (title, artist) if part)
        try:
            yt_hits = await asyncio.to_thread(self.yt.search_songs, query, 5)
        except Exception:
            logger.exception("YouTube Music song search failed for %r", query)
            return None
        return yt_hits[0] if yt_hits else None

    async def resolve_album(
        self, title: str, artist: Optional[str] = None
    ) -> Optional[ResolvedAlbum]:
        try:
            hits = await self.mb.search_releases(title, artist=artist)
        except Exception:
            logger.exception("MusicBrainz release search failed for %r", title)
            hits = []
        for hit in hits:
            if isinstance(hit, dict) and _score(hit) >= self.min_score:
                release_id = hit.get("id")
                if not release_id:
                    continue
                # Full lookup pulls the track list, which search hits omit.
                try:
                    release = await self.mb.get_release(release_id)
                    return self.mb.parse_release(release)
                except Exception:
                    logger.exception("MusicBrainz release lookup failed for %s", release_id)
                    return self.mb.parse_release(hit)

        logger.info("No confident MusicBrainz match for album %r — trying YouTube Music", title)
        query = " ".join(part for part in (title, artist) if part)
        try:
            yt_hits = await asyncio.to_thread(self.yt.search_albums, query, 5)
        except Exception:
            logger.exception("YouTube Music album search failed for %r", query)
            return None
        if not yt_hits:
            return None
        album_hit = yt_hits[0]
        # Pull the full album (track list) when we have an id to look up with.
        lookup_id = album_hit.youtube_browse_id or album_hit.youtube_playlist_id
        if lookup_id:
            try:
                full = await asyncio.to_thread(self.yt.get_album, lookup_id)
                if full:
                    return full
            except Exception:
                logger.exception("YouTube Music album lookup failed for %s", lookup_id)
        return album_hit

    async def resolve_artist(self, name: str) -> Optional[ResolvedArtist]:
        try:
            hits = await self.mb.search_artists(name)
        except Exception:
            logger.exception("MusicBrainz artist search failed for %r", name)
            hits = []
        for hit in hits:
            if isinstance(hit, dict) and _score(hit) >= self.min_score:
                return self.mb.parse_artist_hit(hit)

        logger.info("No confident MusicBrainz match for artist %r — trying YouTube Music", name)
        try:
            yt_hits = await asyncio.to_thread(self.yt.search_artists, name, 5)
        except Exception:
            logger.exception("YouTube Music artist search failed for %r", name)
            return None
        return yt_hits[0] if yt_hits else None

    # ── URL resolution (YouTube Music is the source for pasted links) ─────

    async def resolve_url(self, url: str) -> Optional[ResolvedUrl]:
        """Detect the URL type and resolve it via YouTube Music. Returns None
        for unrecognised URLs. MusicBrainz enrichment of URL-sourced tracks
        happens later in the pipeline (per-track metadata_resolve jobs)."""
        parsed = parse_music_url(url)
        if parsed is None:
            return None
        if parsed.url_type == UrlType.track:
            return await asyncio.to_thread(self.yt.get_track, parsed.id)
        if parsed.url_type == UrlType.album:
            return await asyncio.to_thread(self.yt.get_album, parsed.id)
        if parsed.url_type == UrlType.artist:
            return await asyncio.to_thread(self.yt.get_artist, parsed.id)
        if parsed.url_type == UrlType.playlist:
            return await asyncio.to_thread(self.yt.get_playlist, parsed.id)
        return None
