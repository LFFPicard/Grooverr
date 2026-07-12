"""
Search endpoint (Section 7.1 steps 1-4).

URL queries are detected and resolved directly (track/album/artist/
playlist). Free-text queries hit MusicBrainz first, falling back to
YouTube Music per result category when MusicBrainz has nothing.

Note: MusicBrainz's 1 req/s policy makes a full three-category text search
take ~2-3s. Search is submit-based (not search-as-you-type), so this is
acceptable for v1; logged in Section 11.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import SearchResponse
from app.resolver.schemas import (
    ResolvedAlbum,
    ResolvedArtist,
    ResolvedPlaylist,
    ResolvedTrack,
)
from app.resolver.urls import parse_music_url
from app import runtime

logger = logging.getLogger("grooverr.api.search")

router = APIRouter(prefix="/api/search", tags=["search"])

RESULTS_PER_CATEGORY = 5
FETCH_PER_CATEGORY = 15                      # over-fetch, then re-rank


def _tokens(*values: str | None) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if value:
            tokens.update(value.casefold().replace("’", "'").split())
    return tokens


def _rerank(query: str, candidates: list, variants_of) -> list:
    """Order candidates by token-set similarity to the query. MB relevance
    ranks mashups/bootlegs first on one-box queries because their titles
    embed the artist name; Jaccard similarity over title+artist tokens puts
    the exact real match on top instead.

    variants_of returns alternative text tuples per candidate (e.g. track
    credit vs album artist — "Daft Punk feat. Nile Rodgers" must not lose
    to a remaster credited plainly to "Daft Punk"); the best variant
    counts. Equal similarity breaks toward the earliest release year, same
    original-over-reissue reasoning as the resolver."""
    query_tokens = _tokens(query)

    def key(candidate) -> tuple:
        best = 0.0
        for variant in variants_of(candidate):
            cand_tokens = _tokens(*variant)
            if cand_tokens and query_tokens:
                overlap = len(query_tokens & cand_tokens)
                best = max(best, overlap / len(query_tokens | cand_tokens))
        year = getattr(candidate, "release_year", None)
        return (best, (3000 - year) if year else 0)

    return sorted(candidates, key=key, reverse=True)[:RESULTS_PER_CATEGORY]


@router.get("", response_model=SearchResponse)
async def search(q: str = Query(min_length=1, max_length=500)):
    parsed = parse_music_url(q)
    if parsed is not None:
        result = await runtime.resolver.resolve_url(q)
        if result is None:
            raise HTTPException(
                502, f"Recognised the URL as a {parsed.url_type.value} but could not resolve it"
            )
        response = SearchResponse(query=q, query_type="url", url_type=parsed.url_type.value)
        if isinstance(result, ResolvedTrack):
            response.tracks = [result]
        elif isinstance(result, ResolvedAlbum):
            response.albums = [result]
        elif isinstance(result, ResolvedArtist):
            response.artists = [result]
        elif isinstance(result, ResolvedPlaylist):
            response.playlist = result
        return response

    response = SearchResponse(query=q, query_type="text")
    mb = runtime.resolver.mb
    yt = runtime.resolver.yt

    # MusicBrainz first (Section 7.1 step 3). Freetext (unfielded) queries —
    # users type "title artist" into one box, which a phrase-quoted field
    # query can never match. Studio-first pass for recordings, same
    # reasoning as the resolver's two-pass search.
    try:
        hits = await mb.search_freetext(
            "recording", q, FETCH_PER_CATEGORY,
            extra_terms="status:official AND primarytype:album AND NOT secondarytype:live",
        )
        if not hits:
            hits = await mb.search_freetext("recording", q, FETCH_PER_CATEGORY)
        tracks = [mb.parse_recording_hit(h) for h in hits if isinstance(h, dict)]
        response.tracks = _rerank(
            q, tracks,
            lambda t: [(t.title, t.artist_name), (t.title, t.album_artist)],
        )
    except Exception:
        logger.exception("MusicBrainz recording search failed for %r", q)
    try:
        release_hits = await mb.search_freetext("release", q, FETCH_PER_CATEGORY)
        albums = [mb.parse_release(h) for h in release_hits if isinstance(h, dict)]
        response.albums = _rerank(q, albums, lambda a: [(a.title, a.artist_name)])
    except Exception:
        logger.exception("MusicBrainz release search failed for %r", q)
    try:
        artist_hits = await mb.search_freetext("artist", q, FETCH_PER_CATEGORY)
        artists = [mb.parse_artist_hit(h) for h in artist_hits if isinstance(h, dict)]
        response.artists = _rerank(q, artists, lambda a: [(a.name,)])
    except Exception:
        logger.exception("MusicBrainz artist search failed for %r", q)

    # YouTube Music fallback per empty category.
    if not response.tracks:
        try:
            response.tracks = await asyncio.to_thread(yt.search_songs, q, RESULTS_PER_CATEGORY)
        except Exception:
            logger.exception("YouTube Music song search failed for %r", q)
    if not response.albums:
        try:
            response.albums = await asyncio.to_thread(yt.search_albums, q, RESULTS_PER_CATEGORY)
        except Exception:
            logger.exception("YouTube Music album search failed for %r", q)
    if not response.artists:
        try:
            response.artists = await asyncio.to_thread(yt.search_artists, q, RESULTS_PER_CATEGORY)
        except Exception:
            logger.exception("YouTube Music artist search failed for %r", q)
    return response
