"""
Artist Detail (Section 7.1.1, added 2026-07-14): browse an artist's real
discography by MusicBrainz artist MBID — a structured lookup against a known
entity, never a free-text search, so tribute albums, mashups, and same-title-
different-artist releases cannot appear in the results by construction.

The Section 3 non-goal is *automatic* monitoring (a standing watch for new
releases), not manual browsing — this endpoint and the bulk add-all action
below are both one-time, user-triggered snapshots of the catalog as it
stands right now, with no future-release awareness.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

from app.api.library import _add_album
from app.api.schemas import ArtistDiscographyItem, DiscographyAddAllResponse, Page
from app.db import engine
from app.models import Album, Artist
from app.resolver.engine import _score
from app import runtime

logger = logging.getLogger("grooverr.api.artists")

router = APIRouter(prefix="/api/artists", tags=["artists"])

DISCOGRAPHY_PAGE_SIZE_DEFAULT = 24
DISCOGRAPHY_PAGE_SIZE_MAX = 100
# Bulk add-all pages through the full discography server-side regardless of
# what the client requested for a single page — 25 keeps each browse request
# a reasonable size while still being few requests for a typical discography.
BULK_BROWSE_PAGE_SIZE = 25


async def _ensure_musicbrainz_id(session: Session, artist: Artist) -> Optional[str]:
    """Most Artist rows already carry an MBID (Artist-mode search resolves
    one before creating the row). Rows added before that existed, or via the
    YouTube Music fallback, may not — in that case, identify the artist with
    a single confident MusicBrainz artist-index lookup (same min_score gate
    used everywhere else) and persist the MBID for next time. This still
    only ever *identifies* the entity; the actual catalog browse below is
    always MBID-based, never a text search."""
    if artist.musicbrainz_id:
        return artist.musicbrainz_id
    try:
        hits = await runtime.resolver.mb.search_artists(artist.name, limit=5)
    except Exception:
        logger.exception("MusicBrainz artist lookup failed for %r", artist.name)
        return None
    for hit in hits:
        if isinstance(hit, dict) and _score(hit) >= runtime.resolver.min_score:
            mbid = hit.get("id")
            if mbid:
                artist.musicbrainz_id = mbid
                session.add(artist)
                session.commit()
                return mbid
    return None


@router.get("/{artist_id}/discography", response_model=Page[ArtistDiscographyItem])
async def artist_discography(
    artist_id: str,
    limit: int = Query(default=DISCOGRAPHY_PAGE_SIZE_DEFAULT, ge=1, le=DISCOGRAPHY_PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
):
    with Session(engine) as session:
        artist = session.get(Artist, artist_id)
        if artist is None:
            raise HTTPException(404, "Artist not found")
        artist_name = artist.name
        mbid = await _ensure_musicbrainz_id(session, artist)

    if mbid is None:
        # Nothing to browse by — not an error, just an empty catalog page
        # (an artist row with no confident MusicBrainz identity at all).
        return Page(items=[], total=0, limit=limit, offset=offset)

    groups, total = await runtime.resolver.mb.browse_release_groups_by_artist(
        mbid, limit=limit, offset=offset
    )
    items = []
    with Session(engine) as session:
        for group in groups:
            album = runtime.resolver.mb.parse_release_group_browse_hit(
                group, artist_name=artist_name, artist_mbid=mbid
            )
            in_library = bool(
                album.musicbrainz_id
                and session.exec(
                    select(Album).where(Album.musicbrainz_id == album.musicbrainz_id)
                ).first()
            )
            items.append(
                ArtistDiscographyItem(
                    release_group_id=group.get("id") or "",
                    album=album,
                    in_library=in_library,
                )
            )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/{artist_id}/discography/add-all", response_model=DiscographyAddAllResponse)
async def add_entire_discography(
    artist_id: str,
    quality_kbps: Optional[int] = Query(default=None, ge=32, le=320),
    output_format: Optional[str] = None,
):
    """The one-time bulk snapshot (Section 7.1.1 item 4): enqueues every
    release-group currently returned by MusicBrainz for this artist. Not a
    standing watch — running this again later re-snapshots the catalog as it
    stands then, it does not remember anything from this run."""
    with Session(engine) as session:
        artist = session.get(Artist, artist_id)
        if artist is None:
            raise HTTPException(404, "Artist not found")
        artist_name = artist.name
        mbid = await _ensure_musicbrainz_id(session, artist)

    if mbid is None:
        raise HTTPException(422, "Could not identify this artist on MusicBrainz")

    quality = str(quality_kbps) if quality_kbps else None
    albums_added = 0
    queued_jobs = 0
    already_in_library = 0
    offset = 0
    while True:
        groups, total = await runtime.resolver.mb.browse_release_groups_by_artist(
            mbid, limit=BULK_BROWSE_PAGE_SIZE, offset=offset
        )
        if not groups:
            break
        for group in groups:
            resolved = runtime.resolver.mb.parse_release_group_browse_hit(
                group, artist_name=artist_name, artist_mbid=mbid
            )
            if not resolved.musicbrainz_id:
                logger.warning(
                    "Skipping %r in bulk add for %r — release-group has no releases",
                    resolved.title, artist_name,
                )
                continue
            try:
                result = await _add_album(resolved, quality=quality, output_format=output_format)
            except HTTPException:
                logger.warning(
                    "Skipping %r in bulk add for %r — could not resolve its track list",
                    resolved.title, artist_name,
                )
                continue
            albums_added += 1
            queued_jobs += result.queued_jobs
            already_in_library += result.already_in_library
        offset += len(groups)
        if offset >= total:
            break

    return DiscographyAddAllResponse(
        artist_id=artist_id,
        albums_added=albums_added,
        queued_jobs=queued_jobs,
        already_in_library=already_in_library,
    )
