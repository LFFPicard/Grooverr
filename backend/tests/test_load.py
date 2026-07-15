"""
Batch 10 load test (grooverr.md Section 10): hammer the queue with 50+
simultaneous adds and confirm no deadlocks or corrupted queue state.

Uses a real ASGI transport (not TestClient's single-threaded sync client)
so requests genuinely interleave via asyncio, exercising real concurrent
SQLite writes through app.db's WAL-mode engine — the same condition actual
concurrent users hitting the API at once would produce.
"""
import asyncio

import httpx
import pytest
from sqlmodel import Session, select

from app.db import engine
from app.main import app
from app.models import Album, JobType, QueueItem, Track
from app.resolver.schemas import MetadataSource, ResolvedAlbum, ResolvedTrack


def resolved_album(mbid: str, track_count: int = 3):
    return ResolvedAlbum(
        title=f"Load Test Album {mbid}",
        artist_name="Load Test Artist",
        album_type="album",
        release_year=2020,
        total_tracks=track_count,
        musicbrainz_id=mbid,
        musicbrainz_artist_id="load-artist",
        cover_art_url="https://example.invalid/cover.jpg",
        tracks=[
            ResolvedTrack(
                title=f"Track {n}", artist_name="Load Test Artist",
                album_artist="Load Test Artist", album_title=f"Load Test Album {mbid}",
                track_number=n, disc_number=1, duration_seconds=200,
                musicbrainz_id=f"rec-{mbid}-{n}", musicbrainz_release_id=mbid,
                source=MetadataSource.musicbrainz,
            )
            for n in range(1, track_count + 1)
        ],
        source=MetadataSource.musicbrainz,
    )


async def test_50_concurrent_album_adds_no_deadlock_or_corruption(clean_db):
    """50 distinct albums (3 tracks each = 150 tracks, 150 download jobs)
    added truly concurrently. Every request must succeed with a clean 202,
    and the resulting DB state must be exactly what 50 sequential adds
    would have produced — no lost writes, no duplicate rows, no jobs
    dropped by a lock collision."""
    n_albums = 55
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async def add_one(i: int):
            body = {
                "type": "album",
                "album": resolved_album(f"load-{i}").model_dump(mode="json"),
                "quality_kbps": 192,
            }
            return await client.post("/api/library/add", json=body)

        responses = await asyncio.gather(
            *(add_one(i) for i in range(n_albums)), return_exceptions=True
        )

    exceptions = [r for r in responses if isinstance(r, BaseException)]
    assert not exceptions, f"{len(exceptions)} requests raised (deadlock/lock errors): {exceptions[:3]}"

    statuses = [r.status_code for r in responses]
    failures = [(i, r.status_code, r.text) for i, r in enumerate(responses) if r.status_code != 202]
    assert not failures, f"{len(failures)}/{n_albums} adds failed: {failures[:5]}"

    with Session(engine) as session:
        albums = session.exec(select(Album)).all()
        tracks = session.exec(select(Track)).all()
        download_jobs = session.exec(
            select(QueueItem).where(QueueItem.job_type == JobType.download)
        ).all()

    assert len(albums) == n_albums, f"expected {n_albums} albums, found {len(albums)} — rows lost or duplicated"
    assert len(tracks) == n_albums * 3, f"expected {n_albums * 3} tracks, found {len(tracks)}"
    assert len(download_jobs) == n_albums * 3, (
        f"expected {n_albums * 3} download jobs, found {len(download_jobs)} — "
        "a concurrent write collision dropped or duplicated queue rows"
    )
    # No track should have been enqueued twice (queue corruption symptom).
    track_ids_with_jobs = [j.track_id for j in download_jobs]
    assert len(track_ids_with_jobs) == len(set(track_ids_with_jobs)), (
        "duplicate download jobs for the same track — queue state corrupted under concurrency"
    )


async def test_50_concurrent_adds_of_the_same_album_stay_idempotent(clean_db):
    """Worst-case race: 50 concurrent requests to add the SAME album (e.g. a
    user double/triple/50-tuple-clicking Add, or a flaky client retrying).
    Must dedupe to exactly one Album row and one set of tracks/jobs — never
    N duplicate album rows from a check-then-insert race."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async def add_same():
            body = {
                "type": "album",
                "album": resolved_album("same-album", track_count=5).model_dump(mode="json"),
                "quality_kbps": 192,
            }
            return await client.post("/api/library/add", json=body)

        responses = await asyncio.gather(*(add_same() for _ in range(50)), return_exceptions=True)

    exceptions = [r for r in responses if isinstance(r, BaseException)]
    assert not exceptions, f"{len(exceptions)} requests raised: {exceptions[:3]}"
    assert all(r.status_code == 202 for r in responses), [r.status_code for r in responses if r.status_code != 202]

    with Session(engine) as session:
        albums = session.exec(
            select(Album).where(Album.musicbrainz_id == "same-album")
        ).all()
        tracks = session.exec(select(Track).where(Track.album_id == albums[0].id)).all() if albums else []

    assert len(albums) == 1, f"expected exactly 1 Album row for 50 concurrent adds of the same album, found {len(albums)} — race in _find_or_create_album"
    assert len(tracks) == 5, f"expected 5 tracks, found {len(tracks)}"
