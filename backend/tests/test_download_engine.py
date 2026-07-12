"""
Download engine orchestration tests — yt-dlp is monkeypatched to produce a
local silent file (no network); everything else (matching, tagging, path
placement) runs for real.
"""
import pytest

import app.downloader.engine as engine_module
from app.downloader.engine import DownloadEngine, DownloadFailure
from app.resolver.schemas import MetadataSource, ResolvedTrack
from tests.test_tagger import make_silent_file
from app.downloader.ytdlp import resolve_ffmpeg_path


@pytest.fixture(scope="module")
def ffmpeg():
    path = resolve_ffmpeg_path()
    if not path:
        pytest.skip("no ffmpeg available")
    return path


def track(**overrides):
    fields = dict(
        title="Supersymmetry",
        artist_name="Arcade Fire",
        album_title="Reflektor",
        track_number=3,
        disc_number=2,
        release_year=2013,
        musicbrainz_id="rec-mbid",
        musicbrainz_release_id="rel-mbid",
        musicbrainz_artist_id="artist-mbid",
        youtube_video_id="vid123",
        source=MetadataSource.musicbrainz,
    )
    fields.update(overrides)
    return ResolvedTrack(**fields)


class NoSearchYT:
    def search_songs(self, query, limit=10):
        return []

    def search_videos(self, query, limit=10):
        return []


async def test_full_pipeline_offline(ffmpeg, tmp_path, monkeypatch):
    def fake_download(video_id, dest_dir, output_format, quality_kbps, ffmpeg_path,
                      progress_callback=None):
        assert video_id == "vid123"
        if progress_callback:
            progress_callback(50)
        produced = make_silent_file(ffmpeg, dest_dir, output_format)
        return produced.rename(dest_dir / f"{video_id}.{output_format}")

    monkeypatch.setattr(engine_module, "download_audio", fake_download)
    engine = DownloadEngine(music_root=str(tmp_path / "music"), ytmusic=NoSearchYT())
    result = await engine.download_track(track(), output_format="mp3", multi_disc=True)

    from pathlib import Path
    final = Path(result.file_path)
    # Exact Section 6 path, disc prefix included (multi-disc).
    assert final == tmp_path / "music" / "Arcade Fire" / "Reflektor (2013)" / "2-03 - Supersymmetry.mp3"
    assert final.is_file()
    assert result.audio_source == "youtube-music"
    assert result.audio_source_url == "https://music.youtube.com/watch?v=vid123"
    assert result.bitrate_kbps and result.bitrate_kbps > 0
    assert not result.cover_embedded            # no cover URL → warning, not failure
    assert any("cover art" in w.lower() for w in result.warnings)

    import mutagen
    audio = mutagen.File(final)
    assert str(audio.tags["TIT2"]) == "Supersymmetry"
    assert str(audio.tags["TXXX:MusicBrainz Album Id"]) == "rel-mbid"


async def test_multi_disc_defaults_from_disc_number(ffmpeg, tmp_path, monkeypatch):
    monkeypatch.setattr(
        engine_module, "download_audio",
        lambda video_id, dest_dir, output_format, quality_kbps, ffmpeg_path, progress_callback=None:
            make_silent_file(ffmpeg, dest_dir, output_format),
    )
    engine = DownloadEngine(music_root=str(tmp_path / "music"), ytmusic=NoSearchYT())
    # disc_number=2 with multi_disc unspecified → prefix inferred.
    result = await engine.download_track(track(), output_format="mp3")
    assert result.file_path.endswith("2-03 - Supersymmetry.mp3")


async def test_no_match_is_a_specific_failure(tmp_path):
    engine = DownloadEngine(music_root=str(tmp_path), ytmusic=NoSearchYT())
    with pytest.raises(DownloadFailure, match="No YouTube Music or YouTube match"):
        await engine.download_track(track(youtube_video_id=None))


async def test_ytdlp_failure_surfaces_as_download_failure(tmp_path, monkeypatch):
    from app.downloader.ytdlp import YtdlpDownloadError

    def boom(*args, **kwargs):
        raise YtdlpDownloadError("simulated: video unavailable")

    monkeypatch.setattr(engine_module, "download_audio", boom)
    engine = DownloadEngine(music_root=str(tmp_path), ytmusic=NoSearchYT())
    with pytest.raises(DownloadFailure, match="video unavailable"):
        await engine.download_track(track())
