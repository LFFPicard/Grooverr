"""
MusicBrainz API client (direct REST, JSON web service v2).

- Proper User-Agent string is mandatory per MusicBrainz usage policy.
- Rate limited to 1 request/second (their documented limit) via an asyncio
  lock — all requests through one client instance share the limiter.
- Every field read from API responses uses safe .get() access with defaults,
  never direct indexing (grooverr.md Section 10, Batch 2 — hard requirement).
"""
import asyncio
import re
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


_LUCENE_SPECIALS = re.compile(r'[+\-&|!(){}\[\]^"~*?:\\/]')


def _lucene_strip(value: str) -> str:
    """Neutralise Lucene operators in raw user text (freetext search)."""
    return " ".join(_LUCENE_SPECIALS.sub(" ", value).split())


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


def _primary_credit_name(entity: dict) -> Optional[str]:
    """First credited artist's name alone ('Daft Punk'), without join
    phrases — the album-artist fallback when the release carries no credit."""
    credit = _first(entity.get("artist-credit"))
    name = credit.get("name")
    if not name:
        artist = credit.get("artist")
        name = artist.get("name") if isinstance(artist, dict) else None
    return str(name) if name else None


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


def _top_genre(release: dict) -> Optional[str]:
    """Highest-vote genre name. Release-level genres are usually empty on
    MusicBrainz; release-group genres carry the community votes, so both
    are checked (release first, as the more specific of the two)."""
    group = release.get("release-group")
    candidates = []
    for entity in (release, group if isinstance(group, dict) else {}):
        genres = entity.get("genres")
        if isinstance(genres, list) and genres:
            candidates = [g for g in genres if isinstance(g, dict) and g.get("name")]
            if candidates:
                break
    if not candidates:
        return None
    best = max(candidates, key=lambda g: g.get("count") if isinstance(g.get("count"), int) else 0)
    return best.get("name")


def _release_rank(release: dict, album_hint: Optional[str] = None) -> tuple:
    """Sort key for choosing the most canonical release: exact album-title
    match beats everything, then Official status, then Album-typed release
    groups, then the earliest release date (original pressing over reissue).
    Higher tuple sorts first via max()."""
    rank = 0
    title = release.get("title")
    if album_hint and isinstance(title, str) and title.casefold() == album_hint.casefold():
        rank += 100
    if release.get("status") == "Official":
        rank += 10
    elif release.get("status") == "Bootleg":
        rank -= 10
    group = release.get("release-group")
    if isinstance(group, dict):
        if group.get("primary-type") == "Album":
            rank += 5
        secondary = group.get("secondary-types")
        if isinstance(secondary, list):
            # Studio recordings over live tapings and grab-bag compilations
            # (an exact album_hint match still overrides — +100 dwarfs this).
            if any(isinstance(t, str) and t.lower() == "live" for t in secondary):
                rank -= 8
            if any(isinstance(t, str) and t.lower() == "compilation" for t in secondary):
                rank -= 3
    media = release.get("media")
    for medium in media if isinstance(media, list) else []:
        # Prefer CD/digital pressings: vinyl tracks are numbered by side
        # ("D3"), which breaks numeric track numbering downstream.
        if isinstance(medium, dict) and medium.get("format") in ("CD", "Digital Media"):
            rank += 2
            break
    date = release.get("date")
    date = date if isinstance(date, str) and date else "9999"
    # ISO dates compare correctly as strings; invert so earlier sorts higher.
    return (rank, [-ord(c) for c in date])


def cover_art_url(release_mbid: str, size: int = 500) -> str:
    """Cover Art Archive front-image URL for a release (500/250/1200 sizes)."""
    return f"{COVER_ART_ROOT}/release/{release_mbid}/front-{size}"


def release_group_cover_art_url(release_group_mbid: str, size: int = 500) -> str:
    """Cover Art Archive redirects release-group front-image requests to
    whichever member release it has art for — used for discography browse
    results (Section 7.1.1), which have no single release picked yet."""
    return f"{COVER_ART_ROOT}/release-group/{release_group_mbid}/front-{size}"


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

    def set_user_agent(self, user_agent: str) -> None:
        """Applies immediately to the live client — MusicBrainz rate-limits
        by user-agent string, so a Settings change (Batch 8) must take
        effect without an app restart."""
        self._client.headers["User-Agent"] = user_agent

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
        only_official_studio: bool = False,
    ) -> list[dict]:
        """Raw recording search hits (each includes a 0-100 'score').

        only_official_studio constrains hits to recordings appearing on
        official, non-live album releases — for popular songs MB's relevance
        ordering is otherwise saturated with bootleg live tapings (observed:
        every top-25 hit for 'T.N.T.' + 'AC/DC' was a live bootleg)."""
        terms = [f'recording:"{_lucene_escape(title)}"']
        if artist:
            terms.append(f'artist:"{_lucene_escape(artist)}"')
        if album:
            terms.append(f'release:"{_lucene_escape(album)}"')
        if only_official_studio:
            terms.append("status:official")
            terms.append("primarytype:album")
            terms.append("NOT secondarytype:live")
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

    # ── Browse (structured lookup by known entity, not a text search) ─────

    async def browse_release_groups_by_artist(
        self,
        artist_mbid: str,
        release_types: tuple[str, ...] = ("album", "single", "ep"),
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Section 7.1.1: structured browse of an artist's own release-groups
        by MBID — never a text search, so results are exactly that artist's
        official catalog with no tribute/mashup/same-title-different-artist
        pollution possible by construction. `inc=releases` embeds each
        release-group's member releases (id/title/status/date) so the most
        canonical one (_release_rank) can be picked without an extra
        rate-limited request per item on every page load."""
        params = {
            "artist": artist_mbid,
            "type": "|".join(release_types),
            "limit": limit,
            "offset": offset,
            "inc": "releases",
        }
        data = await self._get("release-group", params)
        groups = data.get("release-groups")
        count = data.get("release-group-count")
        return (
            [g for g in groups if isinstance(g, dict)] if isinstance(groups, list) else [],
            count if isinstance(count, int) else 0,
        )

    async def search_freetext(
        self,
        entity: str,
        query: str,
        limit: int = 5,
        extra_terms: Optional[str] = None,
    ) -> list[dict]:
        """Unfielded search for one-box user queries ('title artist' mixed):
        MB matches bare terms across the entity's indexed fields, which a
        phrase-quoted recording:"…" query cannot do. entity is 'recording',
        'release' or 'artist'; extra_terms appends Lucene field filters."""
        text = _lucene_strip(query)
        if not text:
            return []
        if extra_terms:
            text = f"({text}) AND {extra_terms}"
        data = await self._get(entity, {"query": text, "limit": limit})
        results = data.get(f"{entity}s")
        return results if isinstance(results, list) else []

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
        canonical release it appears on via _release_rank (exact album_hint
        match > official > album-typed > earliest date).
        """
        releases = recording.get("releases")
        candidates = [r for r in releases if isinstance(r, dict)] if isinstance(releases, list) else []
        best_release: dict = (
            max(candidates, key=lambda r: _release_rank(r, album_hint)) if candidates else {}
        )

        medium = _first(best_release.get("media"))
        track_in_medium = _first(medium.get("track"))
        track_number = None
        number = track_in_medium.get("number")
        if isinstance(number, str) and number.isdigit():
            track_number = int(number)
        elif isinstance(number, int):
            track_number = number
        else:
            # Vinyl-style numbers ("D3") aren't numeric — search results carry
            # the matched track's 0-based offset within the medium instead.
            offset = medium.get("track-offset")
            if isinstance(offset, int):
                track_number = offset + 1

        length_ms = recording.get("length")
        release_id = best_release.get("id")
        return ResolvedTrack(
            # The release's track title is what appears on the album (a
            # recording title can carry annotations like "… / [unknown]"
            # for hidden-track merges).
            title=track_in_medium.get("title") or recording.get("title") or "",
            artist_name=_artist_credit_name(recording),
            # Album artist is the release's credit ("Daft Punk"), never the
            # track credit ("Daft Punk feat. Nile Rodgers") — otherwise every
            # guest-feature track lands in its own library folder.
            album_artist=_artist_credit_name(best_release) or _primary_credit_name(recording),
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
        genre = _top_genre(release)

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
                        album_artist=_artist_credit_name(release),
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
    def parse_release_group_browse_hit(
        release_group: dict,
        artist_name: Optional[str] = None,
        artist_mbid: Optional[str] = None,
    ) -> ResolvedAlbum:
        """One release-group from browse_release_groups_by_artist → a
        ResolvedAlbum whose musicbrainz_id is the release-group's own most
        canonical member RELEASE (via _release_rank over the embedded
        `releases` stubs) — so "Add to library" can reuse the exact same
        get_release()-based full-track-list resolution path as any other
        album add, no separate code path needed. total_tracks is left None
        here (browse doesn't include media/track data); the add flow's
        get_release() lookup fills it in, same as a search-result album."""
        rg_id = release_group.get("id")
        releases = release_group.get("releases")
        candidates = [r for r in releases if isinstance(r, dict)] if isinstance(releases, list) else []
        best_release: dict = max(candidates, key=_release_rank) if candidates else {}
        return ResolvedAlbum(
            title=release_group.get("title") or "",
            artist_name=artist_name,
            album_type=_album_type({"release-group": release_group}),
            release_year=_year_from_date(release_group.get("first-release-date")),
            musicbrainz_id=best_release.get("id"),
            musicbrainz_artist_id=artist_mbid,
            cover_art_url=release_group_cover_art_url(rg_id) if rg_id else None,
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
