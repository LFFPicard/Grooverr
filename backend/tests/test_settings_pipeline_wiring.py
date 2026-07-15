"""
Full-audit finding (2026-07-15): Settings must actually be read by the
download pipeline per job, not frozen into DownloadEngine at construction.

Batch 8 already hit this exact bug class once (musicbrainz_user_agent
existed as a setting but nothing read it after startup). These tests pin
the two remaining occurrences found by the audit:

- output_path_template: validated/stored/previewed by the Settings API,
  but Pipeline's DownloadEngine was constructed with the built-in default
  template and never consulted the setting — a user's custom template was
  cosmetic for every real download.
- duration_tolerance_seconds: same disease — the Settings API accepts
  1-60, but the matcher always ran with the constructor default of 5.

Everything below runs the real Pipeline + real DownloadEngine + real path
render + real DB; only the network fetch (yt-dlp) and YT Music lookups are
faked, same as the established queue-test pattern.
"""
import pytest
from sqlmodel import Session

import app.downloader.engine as engine_module
from app.db import engine
from app.downloader.engine import DownloadEngine
from app.models import QueueItem, Track, TrackStatus
from app.queue.pipeline import Pipeline
from app.queue.service import QueueService
from app.resolver.schemas import MetadataSource, ResolvedTrack
from app.settings_store import set_setting
from tests.test_download_engine import ffmpeg  # noqa: F401 — module-scoped fixture
from tests.test_tagger import make_silent_file


class CrossCheckYT:
    """Pre-existing video id resolves 20s off the track's duration; a fresh
    search would return a different id. Which id wins is decided purely by
    the duration tolerance in effect — the behavioural probe for whether
    the duration_tolerance_seconds setting is honored."""

    def get_track(self, video_id):
        return ResolvedTrack(
            title="Real Song", youtube_video_id=video_id,
            duration_seconds=220, source=MetadataSource.youtube_music,
        )

    def search_songs(self, query, limit=10):
        return [ResolvedTrack(
            title="Real Song", artist_name="Real Artist",
            youtube_video_id="fresh-search-id", duration_seconds=200,
            source=MetadataSource.youtube_music,
        )]

    def search_videos(self, query, limit=10):
        return []


def seed_track(session: Session, queue: QueueService, duration=200):
    track_id, _ = queue.add_track_request("Real Song", artist="Real Artist")
    track = session.get(Track, track_id)
    track.duration_seconds = duration
    track.youtube_video_id = "preexisting-id"
    track.track_number = 1
    track.status = TrackStatus.queued
    session.add(track)
    session.commit()
    return track_id


def make_pipeline(tmp_path, ffmpeg_path, monkeypatch):
    def fake_download(video_id, dest_dir, output_format, quality_kbps, ffmpeg_path_,
                      progress_callback=None):
        produced = make_silent_file(ffmpeg_path, dest_dir, output_format)
        return produced.rename(dest_dir / f"{video_id}.{output_format}")

    monkeypatch.setattr(engine_module, "download_audio", fake_download)
    queue = QueueService()
    downloader = DownloadEngine(music_root=str(tmp_path / "music"), ytmusic=CrossCheckYT())
    return queue, Pipeline(queue, downloader=downloader)


async def run_download_job(queue: QueueService, pipeline: Pipeline, track_id: str):
    job_id = queue.enqueue_download(track_id)
    with Session(engine) as session:
        job = session.get(QueueItem, job_id)
    await pipeline.process(job)


async def test_output_path_template_setting_applies_to_downloads(
    clean_db, tmp_path, monkeypatch, ffmpeg  # noqa: F811
):
    """Setting a custom output_path_template must change where the very
    next download lands — no restart, and definitely not 'never'."""
    set_setting("output_path_template", "{MusicRoot}/FLAT/{Artist} -- {Title}.{ext}")
    queue, pipeline = make_pipeline(tmp_path, ffmpeg, monkeypatch)
    with Session(engine) as session:
        track_id = seed_track(session, queue)

    await run_download_job(queue, pipeline, track_id)

    with Session(engine) as session:
        track = session.get(Track, track_id)
    assert track.status == TrackStatus.downloaded, track.error_message
    expected = tmp_path / "music" / "FLAT" / "Real Artist -- Real Song.mp3"
    assert track.file_path == str(expected), (
        f"custom template ignored: landed at {track.file_path!r}, "
        f"expected {str(expected)!r}"
    )
    assert expected.is_file()


async def test_duration_tolerance_setting_applies_to_cross_check(
    clean_db, tmp_path, monkeypatch, ffmpeg  # noqa: F811
):
    """With tolerance widened to 30s in Settings, a pre-existing video id
    20s off the track duration must pass the cross-check and be used; at
    the frozen constructor default of 5s it would be rejected in favour of
    the fresh search hit — so the persisted video id tells us which
    tolerance actually ran."""
    set_setting("duration_tolerance_seconds", 30)
    queue, pipeline = make_pipeline(tmp_path, ffmpeg, monkeypatch)
    with Session(engine) as session:
        track_id = seed_track(session, queue, duration=200)

    await run_download_job(queue, pipeline, track_id)

    with Session(engine) as session:
        track = session.get(Track, track_id)
    assert track.status == TrackStatus.downloaded, track.error_message
    assert track.youtube_video_id == "preexisting-id", (
        "duration_tolerance_seconds setting ignored: the 20s-off pre-existing id "
        f"was rejected (persisted id: {track.youtube_video_id!r}) — the matcher "
        "ran with the frozen constructor default instead of the configured 30s"
    )


async def test_default_tolerance_still_rejects_mismatch(
    clean_db, tmp_path, monkeypatch, ffmpeg  # noqa: F811
):
    """Control case: with no setting override the 5s default must still
    reject the 20s-off pre-existing id (the Batch 6 cross-check fix) —
    honoring the setting must not have loosened the default behaviour."""
    queue, pipeline = make_pipeline(tmp_path, ffmpeg, monkeypatch)
    with Session(engine) as session:
        track_id = seed_track(session, queue, duration=200)

    await run_download_job(queue, pipeline, track_id)

    with Session(engine) as session:
        track = session.get(Track, track_id)
    assert track.status == TrackStatus.downloaded, track.error_message
    assert track.youtube_video_id == "fresh-search-id"
