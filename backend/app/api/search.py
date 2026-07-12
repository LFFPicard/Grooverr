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

    # MusicBrainz first (Section 7.1 step 3) — studio-first for recordings,
    # same reasoning as the resolver's two-pass search.
    try:
        hits = await mb.search_recordings(q, limit=RESULTS_PER_CATEGORY, only_official_studio=True)
        if not hits:
            hits = await mb.search_recordings(q, limit=RESULTS_PER_CATEGORY)
        response.tracks = [mb.parse_recording_hit(h) for h in hits if isinstance(h, dict)]
    except Exception:
        logger.exception("MusicBrainz recording search failed for %r", q)
    try:
        release_hits = await mb.search_releases(q, limit=RESULTS_PER_CATEGORY)
        response.albums = [mb.parse_release(h) for h in release_hits if isinstance(h, dict)]
    except Exception:
        logger.exception("MusicBrainz release search failed for %r", q)
    try:
        artist_hits = await mb.search_artists(q, limit=RESULTS_PER_CATEGORY)
        response.artists = [mb.parse_artist_hit(h) for h in artist_hits if isinstance(h, dict)]
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
