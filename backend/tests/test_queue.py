"""
Queue service + worker pool + pipeline tests. The resolver and download
engine are faked (no network); the queue table, claiming, recovery, retry,
cancel and the worker loop all run for real against a temp SQLite DB.
"""
import asyncio

import pytest
from sqlmodel import Session, select

from app.db import engine
from app.downloader.engine import DownloadResult
from app.models import (
    Album,
    Artist,
    JobStatus,
    JobType,
    Playlist,
    PlaylistTrack,
    QueueItem,
    Track,
    TrackStatus,
)
from app.queue.pipeline import Pipeline
from app.queue.service import QueueService
from app.queue.workers import WorkerPool
from app.resolver.schemas import MetadataSource, ResolvedTrack

RESOLVED = ResolvedTrack(
    title="Real Song",
    artist_name="Real Artist",
    album_artist="Real Artist",
    album_title="Real Album",
    track_number=1,
    disc_number=1,
    duration_seconds=200,
    release_year=2013,
    genre="electronic",
    musicbrainz_id="rec-1",
    musicbrainz_release_id="rel-1",
    musicbrainz_artist_id="art-1",
    cover_art_url="https://example.invalid/cover.jpg",
    source=MetadataSource.musicbrainz,
)


class FakeResolver:
    def __init__(self, result=RESOLVED, fail=False):
        self.result = result
        self.fail = fail

    async def resolve_track(self, title, artist=None, album=None):
        if self.fail:
            raise ConnectionError("resolver exploded")
        return self.result


class FakeDownloader:
    def __init__(self, fail=False, delay=0.0):
        self.fail = fail
        self.delay = delay
        self.calls = []

    async def download_track(self, track, output_format="mp3", quality_kbps=None,
                             album_artist=None, multi_disc=None, match=None,
                             progress_callback=None):
        self.calls.append({"track": track, "format": output_format,
                           "quality": quality_kbps, "multi_disc": multi_disc})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            from app.downloader.engine import DownloadFailure
            raise DownloadFailure("No YouTube Music match found for this track")
        if progress_callback:
            progress_callback(50)
        return DownloadResult(
            file_path=f"/music/x/{track.title}.{output_format}",
            file_format=output_format,
            bitrate_kbps=192,
            audio_source="youtube-music",
            audio_source_url="https://music.youtube.com/watch?v=v1",
            video_id="v1",
            cover_embedded=True,
        )


async def run_pool_until(queue, pipeline, predicate, timeout=5.0, concurrency=1):
    pool = WorkerPool(queue, pipeline=pipeline, concurrency=concurrency)
    pool.start()
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if predicate():
                return
            await asyncio.sleep(0.05)
        raise AssertionError("worker pool did not reach expected state in time")
    finally:
        await pool.stop()


def job_states():
    with Session(engine) as session:
        return {
            (j.job_type.value, j.status.value)
            for j in session.exec(select(QueueItem)).all()
        }


def get_track(track_id):
    with Session(engine) as session:
        return session.get(Track, track_id)


# ── Service basics ─────────────────────────────────────────────────────────

def test_add_track_request_creates_rows_and_job(clean_db):
    queue = QueueService()
    track_id, job_id = queue.add_track_request("Real Song", artist="Real Artist",
                                               quality_kbps=192, output_format="flac")
    with Session(engine) as session:
        track = session.get(Track, track_id)
        assert track is not None and track.status == TrackStatus.queued
        album = session.get(Album, track.album_id)
        artist = session.get(Artist, album.artist_id)
        assert artist.name == "Real Artist"
        job = session.get(QueueItem, job_id)
        assert job.job_type == JobType.metadata_resolve
        assert job.requested_quality == "192"
        assert job.requested_format == "flac"
    assert queue.wake.is_set()


def test_claim_order_priority_then_age(clean_db):
    queue = QueueService()
    _, resolve_job = queue.add_track_request("Song A")
    track_id, _ = queue.add_track_request("Song B")
    download_job = queue.enqueue_download(track_id)

    first = queue.claim_next()
    second = queue.claim_next()
    third = queue.claim_next()
    # Both resolve jobs (priority 50) before the download job (priority 100).
    assert first.job_type == JobType.metadata_resolve
    assert second.job_type == JobType.metadata_resolve
    assert third.id == download_job
    assert queue.claim_next() is None


def test_enqueue_download_is_idempotent_per_track(clean_db):
    queue = QueueService()
    track_id, _ = queue.add_track_request("Song A")
    first = queue.enqueue_download(track_id)
    second = queue.enqueue_download(track_id)   # e.g. re-run recovered resolve job
    assert first == second
    with Session(engine) as session:
        downloads = session.exec(
            select(QueueItem).where(QueueItem.job_type == JobType.download)
        ).all()
        assert len(downloads) == 1
    # A finished download doesn't block a fresh re-download request.
    queue.finish(first)
    third = queue.enqueue_download(track_id)
    assert third != first


def test_recovery_resets_stuck_jobs_and_tracks(clean_db):
    queue = QueueService()
    track_id, _ = queue.add_track_request("Song A")
    job = queue.claim_next()
    assert job.status == JobStatus.active
    with Session(engine) as session:
        track = session.get(Track, track_id)
        track.status = TrackStatus.downloading
        session.add(track)
        session.commit()

    # Simulated unclean restart:
    recovered = queue.recover_stuck_jobs()
    assert recovered == 1
    with Session(engine) as session:
        job = session.get(QueueItem, job.id)
        assert job.status == JobStatus.queued
        assert job.started_at is None
        assert session.get(Track, track_id).status == TrackStatus.queued


def test_retry_only_applies_to_errored_jobs(clean_db):
    queue = QueueService()
    track_id, job_id = queue.add_track_request("Song A")
    assert queue.retry(job_id) is False           # queued, not errored
    claimed = queue.claim_next()
    queue.finish(claimed.id, error="boom")
    with Session(engine) as session:
        track = session.get(Track, track_id)
        track.status = TrackStatus.error
        session.add(track)
        session.commit()
    assert queue.retry(job_id) is True
    with Session(engine) as session:
        assert session.get(QueueItem, job_id).status == JobStatus.queued
        assert session.get(QueueItem, job_id).error_message is None
        assert session.get(Track, track_id).status == TrackStatus.queued


def test_cancel_removes_queued_job_only(clean_db):
    queue = QueueService()
    track_id, job_id = queue.add_track_request("Song A")
    assert queue.cancel(job_id) is True
    with Session(engine) as session:
        assert session.get(QueueItem, job_id) is None
        assert session.get(Track, track_id).status == TrackStatus.missing

    _, job2 = queue.add_track_request("Song B")
    queue.claim_next()
    assert queue.cancel(job2) is False            # active → not cancellable


# ── Full pipeline through the worker pool ──────────────────────────────────

async def test_enqueue_to_downloaded_end_to_end(clean_db):
    queue = QueueService()
    downloader = FakeDownloader()
    pipeline = Pipeline(queue, resolver=FakeResolver(), downloader=downloader)
    track_id, _ = queue.add_track_request("Real Song", artist="Real Artist",
                                          quality_kbps=192)

    await run_pool_until(
        queue, pipeline,
        lambda: get_track(track_id).status == TrackStatus.downloaded,
    )

    track = get_track(track_id)
    assert track.file_path.endswith("Real Song.mp3")
    assert track.bitrate == "192"
    assert track.musicbrainz_id == "rec-1"
    assert track.audio_source.value == "youtube-music"
    assert track.has_artwork is True
    assert track.downloaded_at is not None
    with Session(engine) as session:
        album = session.get(Album, track.album_id)
        assert album.title == "Real Album"        # placeholder got patched
        assert album.genre == "electronic"
        artist = session.get(Artist, album.artist_id)
        assert artist.musicbrainz_id == "art-1"
    # Both jobs completed; quality ceiling propagated resolve → download.
    assert job_states() == {("metadata_resolve", "done"), ("download", "done")}
    assert downloader.calls[0]["quality"] == 192


async def test_download_completion_regenerates_member_playlist_m3u(clean_db):
    """Section 6.1: a track's download completing must regenerate the
    manifest of every playlist it belongs to, via the same _download
    code path — not a separate hook the pipeline could skip."""
    queue = QueueService()
    downloader = FakeDownloader()
    pipeline = Pipeline(queue, resolver=FakeResolver(), downloader=downloader)
    track_id, _ = queue.add_track_request("Real Song", artist="Real Artist")

    with Session(engine) as session:
        playlist = Playlist(name="Auto Playlist")
        session.add(playlist)
        session.flush()
        session.add(PlaylistTrack(playlist_id=playlist.id, track_id=track_id, position=1))
        session.commit()
        playlist_id = playlist.id

    await run_pool_until(
        queue, pipeline,
        lambda: get_track(track_id).status == TrackStatus.downloaded,
    )

    with Session(engine) as session:
        playlist = session.get(Playlist, playlist_id)
        assert playlist.m3u_path is not None
        assert playlist.m3u_generated_at is not None
        track = session.get(Track, track_id)
        content = open(playlist.m3u_path, encoding="utf-8").read()
        assert track.file_path in content
        assert "#EXTM3U" in content


async def test_download_failure_lands_on_track_and_job(clean_db):
    queue = QueueService()
    pipeline = Pipeline(queue, resolver=FakeResolver(), downloader=FakeDownloader(fail=True))
    track_id, _ = queue.add_track_request("Real Song")

    await run_pool_until(
        queue, pipeline,
        lambda: get_track(track_id).status == TrackStatus.error,
    )
    track = get_track(track_id)
    assert "No YouTube Music match" in track.error_message
    with Session(engine) as session:
        download_job = session.exec(
            select(QueueItem).where(QueueItem.job_type == JobType.download)
        ).one()
        assert download_job.status == JobStatus.error
        assert "No YouTube Music match" in download_job.error_message


async def test_resolver_crash_is_not_silently_dropped(clean_db):
    queue = QueueService()
    pipeline = Pipeline(queue, resolver=FakeResolver(fail=True), downloader=FakeDownloader())
    track_id, job_id = queue.add_track_request("Real Song")

    await run_pool_until(
        queue, pipeline,
        lambda: get_track(track_id).status == TrackStatus.error,
    )
    with Session(engine) as session:
        job = session.get(QueueItem, job_id)
        assert job.status == JobStatus.error
        assert "resolver exploded" in job.error_message


async def test_retry_reruns_the_same_duration_cross_check(clean_db, tmp_path, monkeypatch):
    """Section 7.3 / Batch 7 DoD: retrying a track from the Queue must go
    through the identical duration cross-check as the first attempt, not a
    separate retry code path that bypasses it. Proven with a real
    DownloadEngine (not FakeDownloader) wired to a fake YT client whose
    get_track always returns a mismatching duration — download_audio would
    raise if the stale id were ever trusted enough to reach it, on either
    attempt."""
    import app.downloader.engine as engine_module
    from app.downloader.engine import DownloadEngine
    from app.downloader.ytdlp import resolve_ffmpeg_path

    if not resolve_ffmpeg_path():
        pytest.skip("no ffmpeg available")

    class StaleIdYT:
        def __init__(self):
            self.get_track_calls = 0

        def get_track(self, video_id):
            self.get_track_calls += 1
            # Wildly mismatching duration — must never be trusted.
            return ResolvedTrack(title="Wrong Song", youtube_video_id=video_id,
                                 duration_seconds=9999, source=MetadataSource.youtube_music)

        def search_songs(self, query, limit=10):
            return []   # fresh-search fallback also finds nothing

        def search_videos(self, query, limit=10):
            return []

    def unreachable(*args, **kwargs):
        raise AssertionError("download_audio reached — the stale video id was trusted without cross-check")

    monkeypatch.setattr(engine_module, "download_audio", unreachable)

    fake_yt = StaleIdYT()
    queue = QueueService()
    real_engine = DownloadEngine(music_root=str(tmp_path / "music"), ytmusic=fake_yt)
    resolved_with_stale_id = ResolvedTrack(
        title="Real Song", artist_name="Real Artist", duration_seconds=200,
        youtube_video_id="stale-id", musicbrainz_id="rec-1",
        source=MetadataSource.musicbrainz,
    )
    pipeline = Pipeline(queue, resolver=FakeResolver(result=resolved_with_stale_id), downloader=real_engine)
    track_id, _ = queue.add_track_request("Real Song", artist="Real Artist")

    await run_pool_until(queue, pipeline, lambda: get_track(track_id).status == TrackStatus.error)
    assert fake_yt.get_track_calls == 1
    assert get_track(track_id).youtube_video_id == "stale-id"   # never overwritten — no download happened

    with Session(engine) as session:
        download_job = session.exec(
            select(QueueItem).where(QueueItem.job_type == JobType.download)
        ).one()
    assert queue.retry(download_job.id) is True

    await run_pool_until(queue, pipeline, lambda: fake_yt.get_track_calls == 2)
    assert get_track(track_id).status == TrackStatus.error   # rejected again, not bypassed


async def test_concurrency_limit_respected(clean_db):
    queue = QueueService()

    active = {"now": 0, "max": 0}

    class SlowPipeline:
        async def process(self, job):
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            await asyncio.sleep(0.15)
            active["now"] -= 1
            queue.finish(job.id)

    for i in range(6):
        queue.add_track_request(f"Song {i}")

    await run_pool_until(
        queue, SlowPipeline(),
        lambda: job_states() == {("metadata_resolve", "done")},
        concurrency=2, timeout=10,
    )
    assert active["max"] == 2                    # never more than the limit
