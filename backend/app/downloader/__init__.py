"""
Download & tagging engine (Batch 3, grooverr.md Section 10).

Given resolved metadata (Batch 2) it finds the best YouTube Music audio
source, downloads it via yt-dlp at the requested quality ceiling, converts
to the target format, embeds tags + cover art with mutagen, and places the
file per the Section 6 naming convention.
"""
from app.downloader.paths import (
    DEFAULT_PATH_TEMPLATE,
    sanitize_component,
    render_track_path,
)
from app.downloader.matcher import AudioMatch, find_audio_source
from app.downloader.ytdlp import download_audio, resolve_ffmpeg_path, YtdlpDownloadError
from app.downloader.tagger import embed_tags
from app.downloader.engine import DownloadEngine, DownloadResult, DownloadFailure

__all__ = [
    "DEFAULT_PATH_TEMPLATE",
    "sanitize_component",
    "render_track_path",
    "AudioMatch",
    "find_audio_source",
    "download_audio",
    "resolve_ffmpeg_path",
    "YtdlpDownloadError",
    "embed_tags",
    "DownloadEngine",
    "DownloadResult",
    "DownloadFailure",
]
