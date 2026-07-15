"""
Artist Detail endpoint tests (Section 7.1.1) — GET .../discography and POST
.../discography/add-all. Wires a real MetadataResolver to a MockTransport
MusicBrainzClient (not a hand-rolled fake), so the browse/parse/get_release
logic under test is the actual production code, proving the endpoints never
fall back to a text search for the catalog itself.

The mock handler mirrors three real, separately-verified MusicBrainz facts
(browse_release_groups_by_artist can't embed member releases — it 400s on
inc=releases — so the canonical release is resolved via a second browse,
by release-group, only at add-time): release-group browse, release browse
by release-group, and a release lookup.
"""
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import runtime
from app.db import engine
from app.main import app
from app.models import Album, Artist, QueueItem
from app.resolver.engine import MetadataResolver
from app.resolver.musicbrainz import MusicBrainzClient

client = TestClient(app)

LP_MBID = "artist-mbid-lp"

RELEASE_GROUPS = [
    {"id": "rg-hybrid-theory", "title": "Hybrid Theory", "first-release-date": "2000-10-24", "primary-type": "Album"},
    {"id": "rg-meteora", "title": "Meteora", "first-release-date": "2003-03-25", "primary-type": "Album"},
]

# Each release-group has a reissue alongside the original — proves the
# canonical (earliest official) one is picked, not just whatever's first.
RELEASES_BY_GROUP = {
    "rg-hybrid-theory": [
        {"id": "rel-hybrid-theory-reissue", "title": "Hybrid Theory", "status": "Official", "date": "2020-10-24"},
        {"id": "rel-hybrid-theory", "title": "Hybrid Theory", "status": "Official", "date": "2000-10-24"},
    ],
    "rg-meteora": [
        {"id": "rel-meteora", "title": "Meteora", "status": "Official", "date": "2003-03-25"},
    ],
}

FULL_RELEASES = {
    "rel-hybrid-theory": {
        "id": "rel-hybrid-theory", "title": "Hybrid Theory", "date": "2000-10-24",
        "artist-credit": [{"name": "Linkin Park", "artist": {"id": LP_MBID, "name": "Linkin Park"}}],
        "release-group": {"primary-type": "Album"},
        "media": [{"position": 1, "track-count": 1, "tracks": [
            {"position": 1, "title": "Papercut", "length": 185000, "recording": {"id": "rec-papercut"}}
        ]}],
    },
    "rel-meteora": {
        "id": "rel-meteora", "title": "Meteora", "date": "2003-03-25",
        "artist-credit": [{"name": "Linkin Park", "artist": {"id": LP_MBID, "name": "Linkin Park"}}],
        "release-group": {"primary-type": "Album"},
        "media": [{"position": 1, "track-count": 1, "tracks": [
            {"position": 1, "title": "Numb", "length": 187000, "recording": {"id": "rec-numb"}}
        ]}],
    },
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    params = dict(request.url.params)
    if path == "/ws/2/release-group":
        # Structured browse by artist MBID — a plain-text `query` param here
        # would mean this had silently regressed into a text search. Also
        # pins that inc=releases is never sent (real MusicBrainz 400s on it
        # for this resource — verified live, not just assumed).
        assert "query" not in params
        assert "inc" not in params
        assert params.get("artist") == LP_MBID
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 25))
        page = RELEASE_GROUPS[offset:offset + limit]
        return httpx.Response(
            200, json={"release-groups": page, "release-group-count": len(RELEASE_GROUPS)}
        )
    if path == "/ws/2/release" and "release-group" in params:
        assert "query" not in params
        releases = RELEASES_BY_GROUP.get(params["release-group"], [])
        return httpx.Response(200, json={"releases": releases})
    if path.startswith("/ws/2/release/"):
        release = FULL_RELEASES.get(path.rsplit("/", 1)[-1])
        if release is None:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=release)
    if path == "/ws/2/artist":
        return httpx.Response(200, json={"artists": [{"id": LP_MBID, "name": "Linkin Park", "score": 100}]})
    return httpx.Response(404, json={"error": f"unhandled in test: {path} {params}"})


class FakeYT:
    def search_songs(self, q, limit=5):
        return []

    def search_albums(self, q, limit=5):
        return []

    def search_artists(self, q, limit=5):
        return []


@pytest.fixture
def mb_resolver(monkeypatch):
    mb_client = MusicBrainzClient(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), headers={"User-Agent": "test"}
        ),
        rate_limit_seconds=0,
    )
    resolver = MetadataResolver(musicbrainz=mb_client, ytmusic=FakeYT())
    monkeypatch.setattr(runtime, "resolver", resolver)
    yield resolver


def _make_artist(mbid=LP_MBID, name="Linkin Park"):
    with Session(engine) as session:
        artist = Artist(name=name, musicbrainz_id=mbid)
        session.add(artist)
        session.commit()
        session.refresh(artist)
        return artist.id


def test_discography_browses_by_mbid_not_text_search(clean_db, mb_resolver):
    artist_id = _make_artist()
    response = client.get(f"/api/artists/{artist_id}/discography")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    titles = [item["album"]["title"] for item in body["items"]]
    assert titles == ["Hybrid Theory", "Meteora"]
    # Browse alone never resolves a release id (see musicbrainz.py's
    # docstring) — just the release-group id, until something is added.
    assert body["items"][0]["album"]["musicbrainz_id"] is None
    assert body["items"][0]["release_group_id"] == "rg-hybrid-theory"
    assert body["items"][0]["in_library"] is False


def test_discography_flags_items_already_in_library(clean_db, mb_resolver):
    artist_id = _make_artist()
    with Session(engine) as session:
        session.add(Album(artist_id=artist_id, title="Hybrid Theory", musicbrainz_id="rel-hybrid-theory"))
        session.commit()

    body = client.get(f"/api/artists/{artist_id}/discography").json()
    by_title = {item["album"]["title"]: item["in_library"] for item in body["items"]}
    assert by_title["Hybrid Theory"] is True
    assert by_title["Meteora"] is False


def test_discography_404_for_unknown_artist(clean_db, mb_resolver):
    assert client.get("/api/artists/does-not-exist/discography").status_code == 404


def test_discography_backfills_missing_mbid_via_confident_artist_match(clean_db, mb_resolver):
    artist_id = _make_artist(mbid=None)
    body = client.get(f"/api/artists/{artist_id}/discography").json()
    assert body["total"] == 2
    with Session(engine) as session:
        artist = session.get(Artist, artist_id)
        assert artist.musicbrainz_id == LP_MBID  # backfilled and persisted for next time


def test_add_to_library_resolves_canonical_release_from_release_group(clean_db, mb_resolver):
    """The single-item "Add to library" path (POST /api/library/add,
    type=album) must resolve a discography item's release_group_id down to
    the earliest OFFICIAL member release, not the 2020 reissue."""
    artist_id = _make_artist()
    item = client.get(f"/api/artists/{artist_id}/discography").json()["items"][0]
    assert item["album"]["title"] == "Hybrid Theory"

    response = client.post(
        "/api/library/add", json={"type": "album", "album": item["album"]}
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert len(body["added_track_ids"]) == 1
    with Session(engine) as session:
        album = session.get(Album, body["added_album_id"])
        assert album.musicbrainz_id == "rel-hybrid-theory"  # earliest official, not the reissue


async def test_add_entire_discography_enqueues_album_add_jobs_and_returns_fast(clean_db, mb_resolver):
    """Post-audit (Section 11 item 15): the endpoint no longer resolves
    releases synchronously — it browses (cheap), then enqueues one
    album_add job per not-already-owned release, and returns immediately.
    No Album/Track rows exist yet at this point; that's the worker's job."""
    import time
    from app.models import JobType

    artist_id = _make_artist()
    t0 = time.monotonic()
    response = client.post(f"/api/artists/{artist_id}/discography/add-all")
    elapsed = time.monotonic() - t0
    assert response.status_code == 200
    body = response.json()
    assert body["release_groups_found"] == 2
    assert body["jobs_enqueued"] == 2
    assert body["already_in_library"] == 0
    # Rate limiter is 0 in this fixture, so this is really testing "does
    # the request block on N sequential resolves" (it would take several
    # seconds even unlimited) vs "does it return after just the browse".
    assert elapsed < 2.0, f"add-all took {elapsed:.2f}s — looks synchronous again"

    with Session(engine) as session:
        albums = session.exec(select(Album).where(Album.artist_id == artist_id)).all()
        assert albums == []  # nothing resolved yet — that's the worker's job
        jobs = session.exec(
            select(QueueItem).where(QueueItem.job_type == JobType.album_add)
        ).all()
        assert len(jobs) == 2
        assert all(j.status.value == "queued" for j in jobs)
        assert all(j.payload for j in jobs)

    # Now actually run those jobs through the real pipeline (same code a
    # worker would call) to prove they resolve+persist correctly.
    from app.queue.pipeline import Pipeline
    from app.queue.service import QueueService

    queue = QueueService()
    pipeline = Pipeline(queue, resolver=mb_resolver)
    with Session(engine) as session:
        pending = session.exec(
            select(QueueItem).where(QueueItem.job_type == JobType.album_add)
        ).all()
    for job in pending:
        await pipeline.process(job)

    with Session(engine) as session:
        albums = session.exec(select(Album).where(Album.artist_id == artist_id)).all()
        assert {a.title for a in albums} == {"Hybrid Theory", "Meteora"}
        assert {a.musicbrainz_id for a in albums} == {"rel-hybrid-theory", "rel-meteora"}
        download_jobs = session.exec(
            select(QueueItem).where(QueueItem.job_type == JobType.download)
        ).all()
        assert len(download_jobs) == 2  # one track per seeded release

    # "One-time snapshot, not a standing monitor" + retry cost (Section 11
    # item 15's fix): running it again must skip both already-owned
    # releases WITHOUT enqueueing new album_add jobs for them — the whole
    # point is a retry doesn't re-pay the per-release resolve cost.
    response = client.post(f"/api/artists/{artist_id}/discography/add-all")
    body = response.json()
    assert body["release_groups_found"] == 2
    assert body["already_in_library"] == 2
    assert body["jobs_enqueued"] == 0
    with Session(engine) as session:
        albums = session.exec(select(Album).where(Album.artist_id == artist_id)).all()
        assert len(albums) == 2  # no duplicates
        jobs = session.exec(
            select(QueueItem).where(QueueItem.job_type == JobType.album_add)
        ).all()
        assert len(jobs) == 2  # still just the original two — no new ones


def test_add_entire_discography_retry_mid_flight_does_not_duplicate_pending_jobs(clean_db, mb_resolver):
    """Confirmed live against the real Linkin Park discography (2026-07-15):
    the first fix only skipped releases with a *finished* Album row —
    calling add-all again while the first run's jobs were still queued
    (not yet processed) silently double-enqueued every one of them (101
    duplicates out of 219 in the real run). A release must be recognised
    as pending the moment its job is enqueued, not just once it's done."""
    from app.models import JobType

    artist_id = _make_artist()
    first = client.post(f"/api/artists/{artist_id}/discography/add-all").json()
    assert first["jobs_enqueued"] == 2

    # Nothing has been processed yet — both album_add jobs are still
    # 'queued'. This is exactly the "killed/failed partway through" window.
    second = client.post(f"/api/artists/{artist_id}/discography/add-all").json()
    assert second["jobs_enqueued"] == 0, (
        f"retry mid-flight enqueued {second['jobs_enqueued']} new jobs for "
        "already-pending releases — duplicate work"
    )
    assert second["already_in_library"] == 2

    with Session(engine) as session:
        jobs = session.exec(
            select(QueueItem).where(QueueItem.job_type == JobType.album_add)
        ).all()
        assert len(jobs) == 2  # still just the original two


async def test_add_entire_discography_retry_recognizes_canonical_release_title_mismatch(
    clean_db, monkeypatch
):
    """Confirmed live against the real Linkin Park discography (2026-07-15,
    Section 11 item 15): 14 release-groups perpetually re-enqueued on every
    retry, forever, because the canonical *release* _release_rank picks can
    have a different title than its release-group's browse-time title
    (e.g. release-group "Hybrid Theory (20th anniversary edition)" resolves
    to the earliest official release, titled plain "Hybrid Theory") — the
    job finishes successfully (finds/reuses the existing album, no error),
    but a title-string dedup check never recognises it as handled. This
    reproduces that exact shape with dedicated fixture data, isolated from
    the shared module-level fixtures the other tests rely on."""
    import httpx
    from app.resolver.engine import MetadataResolver
    from app.resolver.musicbrainz import MusicBrainzClient
    from app.models import JobType

    mbid = "artist-mbid-anniv"
    rg_id = "rg-anniversary"
    release_id = "rel-original-pressing"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        if path == "/ws/2/release-group":
            offset = int(params.get("offset", 0))
            groups = [{
                "id": rg_id, "title": "Hybrid Theory (20th anniversary edition)",
                "first-release-date": "2020-10-24", "primary-type": "Album",
            }] if offset == 0 else []
            return httpx.Response(200, json={"release-groups": groups, "release-group-count": 1})
        if path == "/ws/2/release" and params.get("release-group") == rg_id:
            return httpx.Response(200, json={"releases": [
                {"id": release_id, "title": "Hybrid Theory", "status": "Official", "date": "2000-10-24"},
            ]})
        if path == f"/ws/2/release/{release_id}":
            return httpx.Response(200, json={
                "id": release_id, "title": "Hybrid Theory", "date": "2000-10-24",
                "artist-credit": [{"name": "Linkin Park", "artist": {"id": mbid, "name": "Linkin Park"}}],
                "release-group": {"primary-type": "Album"},
                "media": [{"position": 1, "track-count": 1, "tracks": [
                    {"position": 1, "title": "Papercut", "length": 185000, "recording": {"id": "rec-papercut"}}
                ]}],
            })
        return httpx.Response(404, json={"error": f"unhandled: {path} {params}"})

    mb_client = MusicBrainzClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"User-Agent": "test"}),
        rate_limit_seconds=0,
    )
    resolver = MetadataResolver(musicbrainz=mb_client)
    monkeypatch.setattr(runtime, "resolver", resolver)

    artist_id = _make_artist(mbid=mbid, name="Linkin Park")
    first = client.post(f"/api/artists/{artist_id}/discography/add-all").json()
    assert first["jobs_enqueued"] == 1

    from app.queue.pipeline import Pipeline
    from app.queue.service import QueueService
    queue = QueueService()
    pipeline = Pipeline(queue, resolver=resolver)
    with Session(engine) as session:
        job = session.exec(select(QueueItem).where(QueueItem.job_type == JobType.album_add)).one()
    await pipeline.process(job)

    with Session(engine) as session:
        job = session.get(QueueItem, job.id)
        assert job.status.value == "done", job.error_message
        albums = session.exec(select(Album).where(Album.artist_id == artist_id)).all()
        # Persisted under the RELEASE's title, not the release-group's.
        assert {a.title for a in albums} == {"Hybrid Theory"}

    # The bug: a title-string check comparing against "Hybrid Theory (20th
    # anniversary edition)" (the release-group's browse title) never
    # matches the persisted "Hybrid Theory" album, so it re-enqueues
    # forever. The fix must recognise this release-group as handled via
    # its own job history, regardless of the title mismatch.
    second = client.post(f"/api/artists/{artist_id}/discography/add-all").json()
    assert second["jobs_enqueued"] == 0, (
        "retried a release-group whose canonical release title differs from "
        "its browse-time title — this would re-pay full resolve cost forever"
    )
    assert second["already_in_library"] == 1
