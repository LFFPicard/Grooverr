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
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlmodel import Session, select

from app.api.schemas import ArtistDiscographyItem, DiscographyAddAllResponse, Page
from app.db import engine
from app.models import Album, Artist, JobStatus, JobType, QueueItem
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


def _already_handled_release_group_ids(session: Session, artist_mbid: str) -> set[str]:
    """release_group_ids that already have a queued/active/done album_add
    job for this artist — i.e. don't need a new one. Deliberately keyed on
    release_group_id from the job's own payload, NOT on the resulting
    Album's title. Two bugs found live against Linkin Park's real
    219-release discography, in order:

    1. Checking only *finished* jobs (Album row exists) let a retry while
       the first run was still mid-flight double-enqueue every not-yet-
       finished release (101 duplicate jobs out of 219 in that run).
    2. Fixing (1) by also checking Album.title == the release-group's
       *browse-time* title still perpetually re-enqueued 14 releases
       forever (anniversary editions, remix singles, box sets) — because
       _resolve_full_album picks the canonical *release* by
       _release_rank, and that release's own title can differ from its
       release-group's title (e.g. release-group "Hybrid Theory (20th
       anniversary edition)" resolves to the earliest official release,
       titled plain "Hybrid Theory" — the exact same album a plain
       "Hybrid Theory" release-group already added). The job completes
       successfully (found the existing album, added nothing new) but the
       title-string check never recognises it as done, so every retry
       re-pays the full network cost for these forever.

    Keying on the job's own release_group_id side-steps both: a release is
    "handled" the instant its job exists with a non-error outcome,
    regardless of what title the resolve step later produces. Only 'error'
    jobs are excluded, so a genuinely failed release still retries."""
    handled = session.exec(
        select(QueueItem.payload).where(
            QueueItem.job_type == JobType.album_add,
            QueueItem.status.in_(  # type: ignore[attr-defined]
                (JobStatus.queued, JobStatus.active, JobStatus.done)
            ),
            QueueItem.payload.is_not(None),  # type: ignore[union-attr]
        )
    ).all()
    ids: set[str] = set()
    for payload in handled:
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            continue
        if data.get("musicbrainz_artist_id") == artist_mbid and data.get("release_group_id"):
            ids.add(data["release_group_id"])
    return ids


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
            # No release id is resolved at browse time (see
            # browse_release_groups_by_artist's docstring), so "already in
            # library" is matched by title within this artist — the same
            # heuristic _find_or_create_album already uses when nothing has
            # a MusicBrainz id to dedupe on.
            in_library = bool(
                session.exec(
                    select(Album).where(
                        Album.artist_id == artist_id, Album.title == album.title
                    )
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
    stands then, it does not remember anything from this run.

    **Post-audit (Section 11 item 15, 2026-07-15):** this used to resolve
    and add every release synchronously in this one request — measured at
    ~7.5 minutes for a 219-release artist, blocking that whole time and
    head-of-line-blocking interactive search behind the shared MusicBrainz
    rate limiter. It now only browses (cheap: ~1 request per
    BULK_BROWSE_PAGE_SIZE releases) and enqueues one `album_add` QueueItem
    per not-already-owned release, returning immediately — each release is
    then resolved+added by a worker via the exact same _add_album() a
    manual single-album add uses (Section 7.5's Queue UI shows the
    progress). Already-owned releases are skipped here, before any
    per-release network resolve — the same title-in-artist heuristic the
    GET .../discography browse already uses for its `in_library` flag —
    so a retry after a partial failure only re-pays the (cheap) browse
    cost, never the per-release resolve cost for releases that already
    succeeded."""
    with Session(engine) as session:
        artist = session.get(Artist, artist_id)
        if artist is None:
            raise HTTPException(404, "Artist not found")
        artist_name = artist.name
        mbid = await _ensure_musicbrainz_id(session, artist)

    if mbid is None:
        raise HTTPException(422, "Could not identify this artist on MusicBrainz")

    quality = str(quality_kbps) if quality_kbps else None
    release_groups_found = 0
    jobs_enqueued = 0
    already_in_library = 0
    offset = 0
    while True:
        groups, total = await runtime.resolver.mb.browse_release_groups_by_artist(
            mbid, limit=BULK_BROWSE_PAGE_SIZE, offset=offset
        )
        if not groups:
            break
        with Session(engine) as session:
            # Recomputed per page (not once, up front): a job enqueued
            # earlier in this same run must also be recognised as handled
            # by the time a later page is processed.
            handled_ids = _already_handled_release_group_ids(session, mbid)
            for group in groups:
                resolved = runtime.resolver.mb.parse_release_group_browse_hit(
                    group, artist_name=artist_name, artist_mbid=mbid
                )
                if not resolved.release_group_id:
                    logger.warning(
                        "Skipping a release-group with no id in bulk add for %r", artist_name,
                    )
                    continue
                release_groups_found += 1
                if resolved.release_group_id in handled_ids:
                    already_in_library += 1
                    continue
                # Fallback for albums in the library through some other
                # path (manual single-album add, pre-dating this job type)
                # that never had an album_add job at all — title match is
                # an approximation, but it's the same one the GET
                # .../discography endpoint already uses for its in_library
                # flag, so this stays consistent with what the UI shows.
                exists = session.exec(
                    select(Album).where(
                        Album.artist_id == artist_id, Album.title == resolved.title
                    )
                ).first()
                if exists is not None:
                    already_in_library += 1
                    continue
                runtime.queue_service.enqueue_album_add(
                    resolved.model_dump_json(), quality=quality, output_format=output_format
                )
                jobs_enqueued += 1
        offset += len(groups)
        if offset >= total:
            break

    return DiscographyAddAllResponse(
        artist_id=artist_id,
        release_groups_found=release_groups_found,
        jobs_enqueued=jobs_enqueued,
        already_in_library=already_in_library,
    )
