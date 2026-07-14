"""
Artist Detail endpoint tests (Section 7.1.1) — GET .../discography and POST
.../discography/add-all. Wires a real MetadataResolver to a MockTransport
MusicBrainzClient (not a hand-rolled fake), so the browse/parse/get_release
logic under test is the actual production code, proving the endpoints never
fall back to a text search for the catalog itself.
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
    {
        "id": "rg-hybrid-theory", "title": "Hybrid Theory", "first-release-date": "2000-10-24",
        "primary-type": "Album",
        "releases": [{"id": "rel-hybrid-theory", "title": "Hybrid Theory", "status": "Official", "date": "2000-10-24"}],
    },
    {
        "id": "rg-meteora", "title": "Meteora", "first-release-date": "2003-03-25",
        "primary-type": "Album",
        "releases": [{"id": "rel-meteora", "title": "Meteora", "status": "Official", "date": "2003-03-25"}],
    },
]

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
        # would mean this had silently regressed into a text search.
        assert "query" not in params
        assert params.get("artist") == LP_MBID
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 25))
        page = RELEASE_GROUPS[offset:offset + limit]
        return httpx.Response(
            200, json={"release-groups": page, "release-group-count": len(RELEASE_GROUPS)}
        )
    if path.startswith("/ws/2/release/"):
        release = FULL_RELEASES.get(path.rsplit("/", 1)[-1])
        if release is None:
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(200, json=release)
    if path == "/ws/2/artist":
        return httpx.Response(200, json={"artists": [{"id": LP_MBID, "name": "Linkin Park", "score": 100}]})
    return httpx.Response(404, json={"error": f"unhandled in test: {path}"})


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
    # The canonical member RELEASE id was resolved, not the release-group id
    # — required so "Add to library" can reuse the ordinary album-add path.
    assert body["items"][0]["album"]["musicbrainz_id"] == "rel-hybrid-theory"
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


def test_add_entire_discography_queues_every_release_and_is_not_a_monitor(clean_db, mb_resolver):
    artist_id = _make_artist()
    response = client.post(f"/api/artists/{artist_id}/discography/add-all")
    assert response.status_code == 200
    body = response.json()
    assert body["albums_added"] == 2
    assert body["queued_jobs"] == 2  # one track per seeded release

    with Session(engine) as session:
        albums = session.exec(select(Album).where(Album.artist_id == artist_id)).all()
        assert {a.title for a in albums} == {"Hybrid Theory", "Meteora"}
        assert len(session.exec(select(QueueItem)).all()) == 2

    # "One-time snapshot, not a standing monitor": running it again just
    # re-adds nothing new (everything's already in the library) — there is
    # no background job left behind that would auto-queue future releases.
    response = client.post(f"/api/artists/{artist_id}/discography/add-all")
    body = response.json()
    assert body["albums_added"] == 2
    assert body["already_in_library"] == 2
    assert body["queued_jobs"] == 0
    with Session(engine) as session:
        albums = session.exec(select(Album).where(Album.artist_id == artist_id)).all()
        assert len(albums) == 2  # no duplicates
