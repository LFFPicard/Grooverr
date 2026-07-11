"""
MusicBrainz API client (direct REST, JSON web service v2).

- Proper User-Agent string is mandatory per MusicBrainz usage policy.
- Rate limited to 1 request/second (their documented limit) via an asyncio
  lock — all requests through one client instance share the limiter.
- Every field read from API responses uses safe .get() access with defaults,
  never direct indexing (grooverr.md Section 10, Batch 2 — hard requirement).
"""
import asyncio
import time
from typing import Any, Optional

import httpx

from app.resolver.schemas import (
    MetadataSource,
    ResolvedArtist,
    ResolvedAlbum,
    ResolvedTrack,
)

MB_API_ROOT = "https://musicbrainz.org/ws/2"
COVER_ART_ROOT = "https://coverartarchive.org"
DEFAULT_USER_AGENT = "Grooverr/0.1.0 ( https://github.com/LFFPicard/Grooverr )"


def _lucene_escape(value: str) -> str:
    """Escape a value for embedding inside a quoted Lucene phrase."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _first(items: Any) -> dict:
    """First element of a list-of-dicts, or {} when absent/malformed."""
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    return {}


def _year_from_date(date: Any) -> Optional[int]:
    """MusicBrainz dates are 'YYYY', 'YYYY-MM' or 'YYYY-MM-DD'."""
    if isinstance(date, str) and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def _artist_credit_name(entity: dict) -> Optional[str]:
    """Joined artist-credit name ('Artist A feat. B') from any MB entity."""
    credits = entity.get("artist-credit")
    if not isinstance(credits, list):
        return None
    parts = []
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        name = credit.get("name") or credit.get("artist", {}).get("name")
        if name:
            parts.append(str(name) + str(credit.get("joinphrase") or ""))
    return "".join(parts).strip() or None


def _artist_credit_mbid(entity: dict) -> Optional[str]:
    credit = _first(entity.get("artist-credit"))
    artist = credit.get("artist")
    if isinstance(artist, dict):
        return artist.get("id")
    return None


def _album_type(release: dict) -> Optional[str]:
    """Map MB release-group types onto Section 5's album_type enum."""
    group = release.get("release-group")
    if not isinstance(group, dict):
        return None
    secondary = group.get("secondary-types")
    if isinstance(secondary, list) and any(
        isinstance(t, str) and t.lower() == "compilation" for t in secondary
    ):
        return "compilation"
    primary = group.get("primary-type")
    if isinstance(primary, str):
        mapped = {"album": "album", "single": "single", "ep": "ep"}.get(primary.lower())
        if mapped:
            return mapped
    return None


def cover_art_url(release_mbid: str, size: int = 500) -> str:
    """Cover Art Archive front-image URL for a release (500/250/1200 sizes)."""
    return f"{COVER_ART_ROOT}/release/{release_mbid}/front-{size}"


class MusicBrainzClient:
    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        rate_limit_seconds: float = 1.0,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.rate_limit_seconds = rate_limit_seconds
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=15.0,
        )
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def close(self):
        await self._client.aclose()

    async def _get(self, path: str, params: dict) -> dict:
        """Rate-limited GET; returns parsed JSON dict ({} on non-dict payloads)."""
        async with self._rate_lock:
            wait = self.rate_limit_seconds - (time.monotonic() - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()
        response = await self._client.get(
            f"{MB_API_ROOT}/{path}", params={**params, "fmt": "json"}
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    # ── Search ────────────────────────────────────────────────────────────

    async def search_recordings(
        self,
        title: str,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Raw recording search hits (each includes a 0-100 'score')."""
        terms = [f'recording:"{_lucene_escape(title)}"']
        if artist:
            terms.append(f'artist:"{_lucene_escape(artist)}"')
        if album:
            terms.append(f'release:"{_lucene_escape(album)}"')
        data = await self._get(
            "recording", {"query": " AND ".join(terms), "limit": limit}
        )
        recordings = data.get("recordings")
        return recordings if isinstance(recordings, list) else []

    async def search_releases(
        self, title: str, artist: Optional[str] = None, limit: int = 10
    ) -> list[dict]:
        terms = [f'release:"{_lucene_escape(title)}"']
        if artist:
            terms.append(f'artist:"{_lucene_escape(artist)}"')
        data = await self._get("release", {"query": " AND ".join(terms), "limit": limit})
        releases = data.get("releases")
        return releases if isinstance(releases, list) else []

    async def search_artists(self, name: str, limit: int = 10) -> list[dict]:
        data = await self._get(
            "artist", {"query": f'artist:"{_lucene_escape(name)}"', "limit": limit}
        )
        artists = data.get("artists")
        return artists if isinstance(artists, list) else []

    # ── Lookup ────────────────────────────────────────────────────────────

    async def get_release(self, release_mbid: str) -> dict:
        """Full release with recordings, artist credits and genres."""
        return await self._get(
            f"release/{release_mbid}",
            {"inc": "recordings+artist-credits+release-groups+genres"},
        )

    # ── Parsers (raw MB dict → Resolved* schema) ──────────────────────────

    @staticmethod
    def parse_recording_hit(recording: dict, album_hint: Optional[str] = None) -> ResolvedTrack:
        """
        Map one recording search hit to a ResolvedTrack, choosing the most
        canonical release it appears on (official > album-typed > dated;
        exact album_hint title match wins outright).
        """
        best_release: dict = {}
        best_rank = -1
        releases = recording.get("releases")
        for release in releases if isinstance(releases, list) else []:
            if not isinstance(release, dict):
                continue
            rank = 0
            title = release.get("title")
            if album_hint and isinstance(title, str) and title.casefold() == album_hint.casefold():
                rank += 100
            if release.get("status") == "Official":
                rank += 10
            group = release.get("release-group")
            if isinstance(group, dict) and group.get("primary-type") == "Album":
                rank += 5
            if release.get("date"):
                rank += 1
            if rank > best_rank:
                best_rank, best_release = rank, release

        medium = _first(best_release.get("media"))
        track_in_medium = _first(medium.get("track"))
        track_number = None
        number = track_in_medium.get("number")
        if isinstance(number, str) and number.isdigit():
            track_number = int(number)
        elif isinstance(number, int):
            track_number = number

        length_ms = recording.get("length")
        release_id = best_release.get("id")
        return ResolvedTrack(
            title=recording.get("title") or "",
            artist_name=_artist_credit_name(recording),
            album_title=best_release.get("title"),
            track_number=track_number,
            disc_number=medium.get("position") if isinstance(medium.get("position"), int) else None,
            duration_seconds=round(length_ms / 1000) if isinstance(length_ms, (int, float)) else None,
            release_year=_year_from_date(best_release.get("date")),
            musicbrainz_id=recording.get("id"),
            musicbrainz_release_id=release_id,
            musicbrainz_artist_id=_artist_credit_mbid(recording),
            cover_art_url=cover_art_url(release_id) if release_id else None,
            source=MetadataSource.musicbrainz,
        )

    @staticmethod
    def parse_release(release: dict) -> ResolvedAlbum:
        """Map a release (search hit or full lookup) to a ResolvedAlbum."""
        release_id = release.get("id")
        genres = release.get("genres")
        genre = _first(genres).get("name") if isinstance(genres, list) else None

        tracks: list[ResolvedTrack] = []
        media = release.get("media")
        total_tracks = 0
        for medium in media if isinstance(media, list) else []:
            if not isinstance(medium, dict):
                continue
            count = medium.get("track-count")
            medium_tracks = medium.get("tracks")
            medium_tracks = medium_tracks if isinstance(medium_tracks, list) else []
            total_tracks += count if isinstance(count, int) else len(medium_tracks)
            for track in medium_tracks:
                if not isinstance(track, dict):
                    continue
                recording = track.get("recording")
                recording = recording if isinstance(recording, dict) else {}
                length_ms = track.get("length") or recording.get("length")
                tracks.append(
                    ResolvedTrack(
                        title=track.get("title") or recording.get("title") or "",
                        artist_name=_artist_credit_name(track) or _artist_credit_name(release),
                        album_title=release.get("title"),
                        track_number=track.get("position") if isinstance(track.get("position"), int) else None,
                        disc_number=medium.get("position") if isinstance(medium.get("position"), int) else None,
                        duration_seconds=round(length_ms / 1000) if isinstance(length_ms, (int, float)) else None,
                        release_year=_year_from_date(release.get("date")),
                        genre=genre,
                        musicbrainz_id=recording.get("id"),
                        musicbrainz_release_id=release_id,
                        musicbrainz_artist_id=_artist_credit_mbid(release),
                        cover_art_url=cover_art_url(release_id) if release_id else None,
                        source=MetadataSource.musicbrainz,
                    )
                )

        if total_tracks == 0:
            count = release.get("track-count")
            total_tracks = count if isinstance(count, int) else 0

        return ResolvedAlbum(
            title=release.get("title") or "",
            artist_name=_artist_credit_name(release),
            album_type=_album_type(release),
            release_year=_year_from_date(release.get("date")),
            total_tracks=total_tracks or None,
            genre=genre,
            musicbrainz_id=release_id,
            musicbrainz_artist_id=_artist_credit_mbid(release),
            cover_art_url=cover_art_url(release_id) if release_id else None,
            tracks=tracks,
            source=MetadataSource.musicbrainz,
        )

    @staticmethod
    def parse_artist_hit(artist: dict) -> ResolvedArtist:
        return ResolvedArtist(
            name=artist.get("name") or "",
            sort_name=artist.get("sort-name"),
            musicbrainz_id=artist.get("id"),
            source=MetadataSource.musicbrainz,
        )
