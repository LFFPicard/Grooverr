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

from app.resolver.musicbrainz import (
    MusicBrainzClient,
    _artist_credit_name,
    _release_rank,
)
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


def _norm(value: Optional[str]) -> str:
    return " ".join(value.casefold().split()) if isinstance(value, str) else ""


def _is_exact_hit(hit: dict, title: str, artist: Optional[str]) -> bool:
    """Title matches the query exactly (and the artist appears in the credit,
    when one was given). Used to admit canonical recordings that MusicBrainz's
    Lucene relevance under-scores relative to remasters/reissues."""
    if _norm(hit.get("title")) != _norm(title):
        return False
    if artist:
        return _norm(artist) in _norm(_artist_credit_name(hit))
    return True


def _best_release_rank(hit: dict, album_hint: Optional[str]) -> tuple:
    releases = hit.get("releases")
    candidates = [r for r in releases if isinstance(r, dict)] if isinstance(releases, list) else []
    return max((_release_rank(r, album_hint) for r in candidates), default=(0, []))


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
        # MusicBrainz Lucene relevance is not canonicality: a 2023 remaster
        # recording can score 100 while the original pressing's recording
        # scores 84. So: exact title+artist matches are admitted down to
        # (min_score - 10) and ranked by the most canonical release they
        # appear on (official > album > earliest date); only when no exact
        # match exists do we fall back to trusting the relevance score.
        hits = [h for h in hits if isinstance(h, dict)]
        exact = [
            h for h in hits
            if _score(h) >= self.min_score - 10 and _is_exact_hit(h, title, artist)
        ]
        if exact:
            best = max(exact, key=lambda h: (_best_release_rank(h, album), _score(h)))
            return self.mb.parse_recording_hit(best, album_hint=album)
        confident = [h for h in hits if _score(h) >= self.min_score]
        if confident:
            best = max(confident, key=lambda h: (_score(h), _best_release_rank(h, album)))
            return self.mb.parse_recording_hit(best, album_hint=album)

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
        # Several releases of the same album often all score 100 (original,
        # reissues, deluxe editions). Rank the confident ones so completeness
        # tracking counts the earliest official release, not a 22-track
        # anniversary reissue.
        confident = [
            hit for hit in hits
            if isinstance(hit, dict) and _score(hit) >= self.min_score and hit.get("id")
        ]
        if confident:
            best = max(confident, key=lambda hit: (_score(hit), _release_rank(hit, title)))
            release_id = best.get("id")
            # Full lookup pulls the track list, which search hits omit.
            try:
                release = await self.mb.get_release(release_id)
                return self.mb.parse_release(release)
            except Exception:
                logger.exception("MusicBrainz release lookup failed for %s", release_id)
                return self.mb.parse_release(best)

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
