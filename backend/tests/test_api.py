"""
Core API layer tests (Batch 5). TestClient without the lifespan context, so
no worker pool runs — enqueued jobs stay in the table for assertions.
External services are faked by patching app.runtime's shared instances.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlmodel import Session, select

from app import runtime
from app.db import engine
from app.main import app
from app.models import Album, JobType, Playlist, QueueItem, Track, TrackStatus
from app.resolver.schemas import (
    MetadataSource,
    ResolvedAlbum,
    ResolvedArtist,
    ResolvedPlaylist,
    ResolvedTrack,
)

client = TestClient(app)


def resolved_album(track_count=3, mbid="rel-1", title=None):
    return ResolvedAlbum(
        title=title or f"Seeded Album {mbid}",
        artist_name="Seeded Artist",
        album_type="album",
        release_year=2013,
        total_tracks=track_count,
        musicbrainz_id=mbid,
        musicbrainz_artist_id="art-1",
        cover_art_url="https://example.invalid/cover.jpg",
        tracks=[
            ResolvedTrack(
                title=f"Track {n}", artist_name="Seeded Artist",
                album_artist="Seeded Artist", album_title=title or f"Seeded Album {mbid}",
                track_number=n, disc_number=1, duration_seconds=200,
                musicbrainz_id=f"rec-{mbid}-{n}", musicbrainz_release_id=mbid,
                source=MetadataSource.musicbrainz,
            )
            for n in range(1, track_count + 1)
        ],
        source=MetadataSource.musicbrainz,
    )


def add_album(track_count=3, mbid="rel-1", title=None):
    response = client.post(
        "/api/library/add",
        json={"type": "album",
              "album": resolved_album(track_count, mbid, title).model_dump(mode="json"),
              "quality_kbps": 192},
    )
    assert response.status_code == 202, response.text
    return response.json()


# ── Add to library ─────────────────────────────────────────────────────────

def test_add_album_creates_rows_and_queues_downloads(clean_db):
    body = add_album(track_count=3)
    assert len(body["added_track_ids"]) == 3
    assert body["queued_jobs"] == 3
    with Session(engine) as session:
        jobs = session.exec(select(QueueItem)).all()
        assert len(jobs) == 3
        assert all(j.job_type == JobType.download for j in jobs)
        assert all(j.requested_quality == "192" for j in jobs)
        album = session.get(Album, body["added_album_id"])
        assert album.total_tracks == 3


def test_add_album_twice_dedupes(clean_db):
    add_album()
    body = add_album()
    assert body["added_track_ids"] == []
    assert body["already_in_library"] == 3


def test_add_track_with_source_id_queues_download(clean_db):
    track = ResolvedTrack(
        title="One Song", artist_name="Someone", album_title="Somewhere",
        musicbrainz_id="rec-x", source=MetadataSource.musicbrainz,
    )
    response = client.post(
        "/api/library/add", json={"type": "track", "track": track.model_dump(mode="json")}
    )
    assert response.status_code == 202
    with Session(engine) as session:
        job = session.exec(select(QueueItem)).one()
        assert job.job_type == JobType.download


def test_add_track_without_ids_queues_resolve(clean_db):
    track = ResolvedTrack(title="Mystery Song", source=MetadataSource.youtube_music)
    response = client.post(
        "/api/library/add", json={"type": "track", "track": track.model_dump(mode="json")}
    )
    assert response.status_code == 202
    with Session(engine) as session:
        job = session.exec(select(QueueItem)).one()
        assert job.job_type == JobType.metadata_resolve


def test_add_playlist_adds_each_track(clean_db):
    playlist = ResolvedPlaylist(
        title="Mix", source=MetadataSource.youtube_music,
        tracks=[
            ResolvedTrack(title="P1", artist_name="A", source=MetadataSource.youtube_music),
            ResolvedTrack(title="P2", artist_name="B", source=MetadataSource.youtube_music),
        ],
    )
    response = client.post(
        "/api/library/add",
        json={"type": "playlist", "playlist": playlist.model_dump(mode="json")},
    )
    assert response.status_code == 202
    assert response.json()["queued_jobs"] == 2


def test_add_playlist_creates_playlist_row_and_links_tracks(clean_db):
    playlist = ResolvedPlaylist(
        title="Road Trip",
        source=MetadataSource.youtube_music,
        youtube_playlist_id="PLxyz",
        tracks=[
            ResolvedTrack(title="P1", artist_name="Artist A", album_title="Album A",
                          youtube_video_id="v1", source=MetadataSource.youtube_music),
            ResolvedTrack(title="P2", artist_name="Artist B", album_title="Album B",
                          youtube_video_id="v2", source=MetadataSource.youtube_music),
        ],
    )
    response = client.post(
        "/api/library/add",
        json={"type": "playlist", "playlist": playlist.model_dump(mode="json")},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["added_playlist_id"]
    assert len(body["added_track_ids"]) == 2
    assert body["queued_jobs"] == 2

    with Session(engine) as session:
        jobs = session.exec(select(QueueItem)).all()
        assert all(j.job_type == JobType.download for j in jobs)  # both carried a video id

    detail = client.get(f"/api/library/playlists/{body['added_playlist_id']}").json()
    assert detail["name"] == "Road Trip"
    assert detail["total_tracks"] == 2
    assert [pt["position"] for pt in detail["tracks"]] == [1, 2]
    assert detail["tracks"][0]["track"]["title"] == "P1"


def test_add_playlist_same_source_id_reuses_playlist_and_dedupes_tracks(clean_db):
    playlist = ResolvedPlaylist(
        title="Road Trip", source=MetadataSource.youtube_music, youtube_playlist_id="PLxyz",
        tracks=[ResolvedTrack(title="P1", youtube_video_id="v1", source=MetadataSource.youtube_music)],
    )
    first = client.post(
        "/api/library/add", json={"type": "playlist", "playlist": playlist.model_dump(mode="json")}
    ).json()
    second = client.post(
        "/api/library/add", json={"type": "playlist", "playlist": playlist.model_dump(mode="json")}
    ).json()
    assert second["added_playlist_id"] == first["added_playlist_id"]
    assert second["added_track_ids"] == []
    assert second["already_in_library"] == 1

    with Session(engine) as session:
        assert session.exec(select(func.count()).select_from(Playlist)).one() == 1


def test_playlist_list_and_complete(clean_db):
    playlist = ResolvedPlaylist(
        title="Mix", source=MetadataSource.youtube_music, youtube_playlist_id="PLabc",
        tracks=[
            ResolvedTrack(title="T1", youtube_video_id="v1", source=MetadataSource.youtube_music),
            ResolvedTrack(title="T2", youtube_video_id="v2", source=MetadataSource.youtube_music),
        ],
    )
    added = client.post(
        "/api/library/add", json={"type": "playlist", "playlist": playlist.model_dump(mode="json")}
    ).json()
    playlist_id = added["added_playlist_id"]

    listing = client.get("/api/library/playlists").json()
    assert listing["total"] == 1
    assert listing["items"][0]["completeness"] == "empty"

    with Session(engine) as session:
        tracks = session.exec(select(Track)).all()
        tracks[0].status = TrackStatus.downloaded
        tracks[1].status = TrackStatus.error
        tracks[1].error_message = "boom"
        for t in tracks:
            session.add(t)
        for job in session.exec(select(QueueItem)):
            session.delete(job)
        session.commit()

    complete = client.post(f"/api/library/playlists/{playlist_id}/complete")
    assert complete.status_code == 200
    assert complete.json()["queued_jobs"] == 1          # only the errored track, not the downloaded one

    detail = client.get(f"/api/library/playlists/{playlist_id}").json()
    assert detail["downloaded_tracks"] == 1
    assert detail["completeness"] == "incomplete"

    assert client.get("/api/library/playlists/nonexistent").status_code == 404
    assert client.post("/api/library/playlists/nonexistent/complete").status_code == 404


def test_add_rejects_bad_format_and_missing_payload(clean_db):
    assert client.post(
        "/api/library/add",
        json={"type": "track", "output_format": "aiff",
              "track": {"title": "X", "source": "musicbrainz"}},
    ).status_code == 422
    assert client.post("/api/library/add", json={"type": "album"}).status_code == 422


# ── Library listing / detail ───────────────────────────────────────────────

def test_album_list_pagination_and_completeness(clean_db):
    add_album(track_count=2, mbid="rel-a")
    add_album(track_count=2, mbid="rel-b")
    with Session(engine) as session:
        album_id = client.get("/api/library/albums").json()["items"][0]["id"]
        for track in session.exec(select(Track).where(Track.album_id == album_id)):
            track.status = TrackStatus.downloaded
            session.add(track)
        session.commit()

    everything = client.get("/api/library/albums").json()
    assert everything["total"] == 2

    page = client.get("/api/library/albums?limit=1&offset=1").json()
    assert page["total"] == 2 and len(page["items"]) == 1

    complete = client.get("/api/library/albums?completeness=complete").json()
    assert complete["total"] == 1
    assert complete["items"][0]["downloaded_tracks"] == 2
    assert complete["items"][0]["completeness"] == "complete"

    empty = client.get("/api/library/albums?completeness=empty").json()
    assert empty["total"] == 1


def test_album_detail_with_tracks(clean_db):
    body = add_album(track_count=3)
    detail = client.get(f"/api/library/albums/{body['added_album_id']}").json()
    assert detail["known_tracks"] == 3
    assert [t["track_number"] for t in detail["tracks"]] == [1, 2, 3]
    assert client.get("/api/library/albums/nonexistent").status_code == 404


def test_artist_listing(clean_db):
    add_album()
    artists = client.get("/api/library/artists").json()
    assert artists["total"] == 1
    assert artists["items"][0]["album_count"] == 1
    assert client.get("/api/library/artists?search=zzz").json()["total"] == 0


# ── Album/track actions ────────────────────────────────────────────────────

def test_complete_album_queues_missing_tracks_only(clean_db):
    body = add_album(track_count=3)
    with Session(engine) as session:
        tracks = session.exec(select(Track)).all()
        tracks[0].status = TrackStatus.downloaded
        tracks[1].status = TrackStatus.error
        tracks[1].error_message = "old failure"
        tracks[2].status = TrackStatus.missing
        for t in tracks:
            session.add(t)
        # Clear the download jobs created by the add.
        for job in session.exec(select(QueueItem)):
            session.delete(job)
        session.commit()

    response = client.post(f"/api/library/albums/{body['added_album_id']}/complete")
    assert response.status_code == 200
    assert response.json()["queued_jobs"] == 2       # error + missing, not downloaded
    with Session(engine) as session:
        statuses = {t.status for t in session.exec(select(Track))}
        assert TrackStatus.downloaded in statuses
        assert TrackStatus.queued in statuses
        assert TrackStatus.error not in statuses


def test_track_download_action(clean_db):
    body = add_album(track_count=1)
    track_id = body["added_track_ids"][0]
    response = client.post(f"/api/library/tracks/{track_id}/download")
    assert response.status_code == 202
    assert response.json()["track_id"] == track_id
    assert client.post("/api/library/tracks/nope/download").status_code == 404


# ── Search ─────────────────────────────────────────────────────────────────

class FakeSearchResolver:
    class _MB:
        async def search_freetext(self, entity, q, limit=5, extra_terms=None):
            if entity == "recording":
                from tests.test_musicbrainz import RECORDING_HIT
                return [RECORDING_HIT]
            return []

        from app.resolver.musicbrainz import MusicBrainzClient as _C
        parse_recording_hit = staticmethod(_C.parse_recording_hit)
        parse_release = staticmethod(_C.parse_release)
        parse_artist_hit = staticmethod(_C.parse_artist_hit)

    class _YT:
        def search_songs(self, q, limit=5):
            return []

        def search_albums(self, q, limit=5):
            return [ResolvedAlbum(title="YT Album", source=MetadataSource.youtube_music)]

        def search_artists(self, q, limit=5):
            return [ResolvedArtist(name="YT Artist", source=MetadataSource.youtube_music)]

    def __init__(self):
        self.mb = self._MB()
        self.yt = self._YT()

    async def resolve_url(self, url):
        return ResolvedTrack(title="URL Track", youtube_video_id="v1",
                             source=MetadataSource.youtube_music)


@pytest.fixture
def fake_resolver(monkeypatch):
    monkeypatch.setattr(runtime, "resolver", FakeSearchResolver())


def test_text_search_mb_first_ytm_fallback_per_category(clean_db, fake_resolver):
    body = client.get("/api/search?q=give life back to music").json()
    assert body["query_type"] == "text"
    assert body["tracks"][0]["musicbrainz_id"] == "rec-mbid-1"   # from MB
    assert body["albums"][0]["title"] == "YT Album"              # YTM fallback
    assert body["artists"][0]["name"] == "YT Artist"             # YTM fallback


def test_url_search_detects_and_resolves(clean_db, fake_resolver):
    body = client.get(
        "/api/search", params={"q": "https://music.youtube.com/watch?v=abc123"}
    ).json()
    assert body["query_type"] == "url"
    assert body["url_type"] == "track"
    assert body["tracks"][0]["title"] == "URL Track"


def test_search_rerank_puts_exact_match_above_mashups():
    from app.api.search import _rerank

    variants = lambda t: [(t.title, t.artist_name), (t.title, t.album_artist)]
    exact = ResolvedTrack(title="Give Life Back to Music", artist_name="Daft Punk",
                          source=MetadataSource.musicbrainz)
    mashup = ResolvedTrack(
        title="Give Life Back to Music (Somebody to Love remix) (Daft Punk vs. Liltommyj)",
        artist_name="Daft Punk vs. Liltommyj", source=MetadataSource.musicbrainz,
    )
    ranked = _rerank("give life back to music daft punk", [mashup, exact], variants)
    assert ranked[0] is exact

    # A featured-guest track credit must not lose to a plainly-credited
    # remaster; equal similarity breaks toward the earlier release.
    original = ResolvedTrack(
        title="Give Life Back to Music", artist_name="Daft Punk feat. Nile Rodgers",
        album_artist="Daft Punk", release_year=2013, source=MetadataSource.musicbrainz,
    )
    remaster = ResolvedTrack(
        title="Give Life Back to Music", artist_name="Daft Punk",
        album_artist="Daft Punk", release_year=2023, source=MetadataSource.musicbrainz,
    )
    ranked = _rerank("give life back to music daft punk", [remaster, original], variants)
    assert ranked[0] is original


# ── Settings ───────────────────────────────────────────────────────────────

def test_settings_roundtrip_and_validation(clean_db):
    defaults = client.get("/api/settings").json()
    assert defaults["download_concurrency"] == 3
    assert defaults["default_output_format"] == "mp3"

    updated = client.put(
        "/api/settings",
        json={"download_concurrency": 5, "default_quality_ceiling": 256,
              "default_output_format": "flac"},
    ).json()
    assert updated["download_concurrency"] == 5
    assert client.get("/api/settings").json()["default_output_format"] == "flac"

    assert client.put("/api/settings", json={"download_concurrency": 99}).status_code == 422
    assert client.put("/api/settings", json={"default_output_format": "aiff"}).status_code == 422
    assert client.put(
        "/api/settings", json={"output_path_template": "{MusicRoot}/{Bogus}.{ext}"}
    ).status_code == 422
    assert client.put(
        "/api/settings",
        json={"output_path_template": "{MusicRoot}/{Artist}/{Title}.{ext}"},
    ).status_code == 200
    assert client.put("/api/settings", json={}).status_code == 422


def test_playlist_output_folder_setting_roundtrip_and_validation(clean_db):
    assert client.get("/api/settings").json()["playlist_output_folder"] is None

    updated = client.put(
        "/api/settings", json={"playlist_output_folder": "My Mixes"}
    ).json()
    assert updated["playlist_output_folder"] == "My Mixes"

    # Normalizes slashes/whitespace.
    normalized = client.put(
        "/api/settings", json={"playlist_output_folder": "  /Nested\\Folder/  "}
    ).json()
    assert normalized["playlist_output_folder"] == "Nested/Folder"

    for bad in ["", "   ", "../escape", "a/../b", "/"]:
        response = client.put("/api/settings", json={"playlist_output_folder": bad})
        assert response.status_code == 422, f"{bad!r} should have been rejected"

    illegal_chars = client.put(
        "/api/settings", json={"playlist_output_folder": "Mixes: Vol 1?"}
    )
    assert illegal_chars.status_code == 422
    assert "Mixes- Vol 1-" in illegal_chars.json()["detail"]

    reset = client.put("/api/settings", json={"playlist_output_folder": None}).json()
    assert reset["playlist_output_folder"] is None


def test_musicbrainz_user_agent_applies_to_live_client(clean_db):
    """MusicBrainz rate-limits by user-agent — a Settings change must take
    effect immediately, not just on next restart (Batch 8)."""
    from app.resolver.musicbrainz import DEFAULT_USER_AGENT

    response = client.put("/api/settings", json={"musicbrainz_user_agent": "GrooverrTest/9.9"})
    assert response.status_code == 200
    assert runtime.resolver.mb._client.headers["User-Agent"] == "GrooverrTest/9.9"

    # Explicit null resets to the built-in default, live.
    client.put("/api/settings", json={"musicbrainz_user_agent": None})
    assert runtime.resolver.mb._client.headers["User-Agent"] == DEFAULT_USER_AGENT


VALID_COOKIES_TXT = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tCONSENT\tYES+1\n"
    ".youtube.com\tTRUE\t/\tTRUE\t2147483647\tVISITOR_INFO1_LIVE\tabc123\n"
)


def test_youtube_cookies_upload_status_and_delete(clean_db):
    assert client.get("/api/settings/youtube-cookies").json() == {
        "configured": False, "uploaded_at": None,
    }

    upload = client.post(
        "/api/settings/youtube-cookies",
        files={"file": ("cookies.txt", VALID_COOKIES_TXT.encode(), "text/plain")},
    )
    assert upload.status_code == 201
    body = upload.json()
    assert body["configured"] is True
    assert body["uploaded_at"] is not None

    status = client.get("/api/settings/youtube-cookies").json()
    assert status["configured"] is True
    assert status["uploaded_at"] == body["uploaded_at"]

    deleted = client.delete("/api/settings/youtube-cookies")
    assert deleted.status_code == 200
    assert deleted.json() == {"configured": False, "uploaded_at": None}
    assert client.get("/api/settings/youtube-cookies").json()["configured"] is False


def test_youtube_cookies_rejects_bad_uploads(clean_db):
    empty = client.post(
        "/api/settings/youtube-cookies", files={"file": ("cookies.txt", b"", "text/plain")}
    )
    assert empty.status_code == 422

    not_cookies = client.post(
        "/api/settings/youtube-cookies",
        files={"file": ("cookies.txt", b"this is just some random text file", "text/plain")},
    )
    assert not_cookies.status_code == 422

    too_big = client.post(
        "/api/settings/youtube-cookies",
        files={"file": ("cookies.txt", b"x" * 2_000_000, "text/plain")},
    )
    assert too_big.status_code == 422

    binary = client.post(
        "/api/settings/youtube-cookies",
        files={"file": ("cookies.txt", bytes([0xFF, 0xFE, 0x00, 0x80]), "application/octet-stream")},
    )
    assert binary.status_code == 422

    # None of the rejected uploads should have configured anything.
    assert client.get("/api/settings/youtube-cookies").json()["configured"] is False


def test_preview_path_renders_real_examples(clean_db):
    response = client.get(
        "/api/settings/preview-path",
        params={"template": "{MusicRoot}/{AlbumArtist}/{Album} ({ReleaseYear})/{DiscNumber-}{TrackNumber} - {Title}.{ext}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["single_disc_example"] == (
        "/music/Daft Punk/Random Access Memories (2013)/01 - Give Life Back to Music.flac"
    )
    assert body["multi_disc_example"] == (
        "/music/Arcade Fire/Reflektor (2013)/2-03 - Supersymmetry.mp3"
    )


def test_preview_path_uses_saved_setting_when_no_override(clean_db):
    client.put("/api/settings", json={"output_path_template": "{MusicRoot}/{Artist}/{Title}.{ext}"})
    body = client.get("/api/settings/preview-path").json()
    assert body["single_disc_example"] == "/music/Daft Punk/Give Life Back to Music.flac"


def test_preview_path_rejects_bad_template(clean_db):
    response = client.get(
        "/api/settings/preview-path", params={"template": "{MusicRoot}/{Bogus}.{ext}"}
    )
    assert response.status_code == 422


# ── Queue enrichment ────────────────────────────────────────────────────────

def test_queue_listing_includes_artist_album_context(clean_db):
    add_album(track_count=1)
    body = client.get("/api/queue").json()
    assert body["items"][0]["artist_name"] == "Seeded Artist"
    assert body["items"][0]["album_title"] == "Seeded Album rel-1"


# ── Activity feed ────────────────────────────────────────────────────────

def test_activity_feed_empty_by_default(clean_db):
    add_album(track_count=1)                          # only queues a job, doesn't finish it
    assert client.get("/api/activity").json()["items"] == []


def test_activity_feed_shows_finished_jobs_newest_first(clean_db):
    body = add_album(track_count=2)
    with Session(engine) as session:
        jobs = session.exec(select(QueueItem)).all()
        jobs[0].status = "done"
        from datetime import datetime, timedelta
        jobs[0].finished_at = datetime.utcnow() - timedelta(minutes=5)
        jobs[1].status = "error"
        jobs[1].error_message = "No YouTube Music match found for this track"
        jobs[1].finished_at = datetime.utcnow()
        session.add(jobs[0])
        session.add(jobs[1])
        session.commit()

    items = client.get("/api/activity?limit=10").json()["items"]
    assert len(items) == 2
    assert items[0]["status"] == "error"               # most recent first
    assert items[0]["error_message"] == "No YouTube Music match found for this track"
    assert items[0]["artist_name"] == "Seeded Artist"
    assert items[1]["status"] == "done"


# ── Stats ──────────────────────────────────────────────────────────────────

def test_stats_aggregates(clean_db):
    add_album(track_count=2)                          # 2 queued download jobs
    with Session(engine) as session:
        track = session.exec(select(Track)).first()
        track.status = TrackStatus.downloaded
        session.add(track)
        session.commit()
    body = client.get("/api/stats").json()
    assert body["queued"] == 2
    assert body["library_tracks"] == 1
    assert body["library_albums"] == 1
    assert body["incomplete_albums"] == 1


# ── Scale (Batch 5 DoD: 1,000+ albums, not a toy dataset) ──────────────────

def test_library_pagination_at_scale(clean_db):
    import time
    from app.api.seed import seed_library

    counts = seed_library(album_count=1200, tracks_per_album=10)
    assert counts["albums"] == 1200 and counts["tracks"] == 12000

    start = time.perf_counter()
    page = client.get("/api/library/albums?limit=50&offset=600&sort=title").json()
    elapsed = time.perf_counter() - start
    assert page["total"] == 1200
    assert len(page["items"]) == 50
    assert elapsed < 1.0, f"page fetch took {elapsed:.3f}s on 1200 albums"

    incomplete = client.get("/api/library/albums?completeness=incomplete&limit=50").json()
    assert 0 < incomplete["total"] < 1200
    assert all(i["completeness"] == "incomplete" for i in incomplete["items"])

    # Artist-filtered listing hits the artist_id index.
    artist_id = page["items"][0]["artist_id"]
    by_artist = client.get(f"/api/library/albums?artist_id={artist_id}").json()
    assert 0 < by_artist["total"] < 200
    assert all(i["artist_id"] == artist_id for i in by_artist["items"])


def test_playlist_pagination_at_scale(clean_db):
    import time
    from app.api.seed import seed_library, seed_playlists

    seed_library(album_count=400, tracks_per_album=10)
    counts = seed_playlists(playlist_count=60, tracks_per_playlist=15)
    assert counts["playlists"] == 60

    start = time.perf_counter()
    page = client.get("/api/library/playlists?limit=20&offset=40").json()
    elapsed = time.perf_counter() - start
    assert page["total"] == 60
    assert len(page["items"]) == 20
    assert elapsed < 1.0, f"page fetch took {elapsed:.3f}s on 60 playlists"
    assert all(0 <= p["downloaded_tracks"] <= p["total_tracks"] for p in page["items"])


def test_openapi_lists_every_endpoint(clean_db):
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for expected in (
        "/api/search", "/api/library/add", "/api/library/albums",
        "/api/library/albums/{album_id}", "/api/library/albums/{album_id}/complete",
        "/api/library/tracks/{track_id}/download", "/api/library/artists",
        "/api/queue", "/api/queue/add", "/api/queue/{job_id}/retry",
        "/api/queue/{job_id}", "/api/queue/events", "/api/settings",
        "/api/stats", "/api/health",
    ):
        assert expected in paths, f"{expected} missing from OpenAPI"
    # Response schemas are declared (not bare 200s) on the core reads.
    library_get = paths["/api/library/albums"]["get"]["responses"]["200"]
    assert "$ref" in str(library_get["content"]["application/json"]["schema"])
