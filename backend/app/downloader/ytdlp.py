"""
yt-dlp wrapper — downloads audio for a video id at a quality ceiling and
converts to the target output format via ffmpeg.

Blocking (yt-dlp is sync); the engine wraps calls in asyncio.to_thread.
"""
import os
import shutil
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

from app.settings_store import config_dir

# Output format → yt-dlp FFmpegExtractAudio codec name.
_CODEC_BY_FORMAT = {
    "mp3": "mp3",
    "flac": "flac",
    "m4a": "m4a",
    "opus": "opus",
    "wav": "wav",
    "ogg": "vorbis",
}
SUPPORTED_FORMATS = tuple(_CODEC_BY_FORMAT)
LOSSY_FORMATS = ("mp3", "m4a", "opus", "ogg")

# Batch 8: optional YouTube cookie export (Netscape cookies.txt format),
# uploaded via Settings. Stored in CONFIG_DIR — never the music volume.
YOUTUBE_COOKIES_FILENAME = "youtube_cookies.txt"


def youtube_cookies_path() -> Path:
    return Path(config_dir()) / YOUTUBE_COOKIES_FILENAME


def resolve_cookies_path() -> Optional[str]:
    path = youtube_cookies_path()
    return str(path) if path.is_file() else None


class YtdlpDownloadError(Exception):
    pass


def resolve_ffmpeg_path() -> Optional[str]:
    """ffmpeg binary: GROOVERR_FFMPEG env override > system PATH >
    imageio-ffmpeg's bundled static build (dev convenience — the Docker
    image installs a real ffmpeg)."""
    override = os.environ.get("GROOVERR_FFMPEG")
    if override:
        return override
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def download_audio(
    video_id: str,
    dest_dir: Path,
    output_format: str = "mp3",
    quality_kbps: Optional[int] = None,
    ffmpeg_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int], None]] = None,
    cookies_path: Optional[str] = "unset",
) -> Path:
    """Download + convert one video's audio. Returns the converted file path
    inside dest_dir. Raises YtdlpDownloadError on any failure.

    cookies_path defaults to whatever's currently uploaded in Settings
    (checked fresh per call, not cached) — pass None explicitly to force no
    cookies, or a path to override."""
    if output_format not in _CODEC_BY_FORMAT:
        raise YtdlpDownloadError(
            f"Unsupported output format {output_format!r} (supported: {', '.join(SUPPORTED_FORMATS)})"
        )
    ffmpeg_path = ffmpeg_path or resolve_ffmpeg_path()
    if not ffmpeg_path:
        raise YtdlpDownloadError(
            "No ffmpeg binary found (set GROOVERR_FFMPEG or install ffmpeg)"
        )

    dest_dir.mkdir(parents=True, exist_ok=True)
    # Broad fallback selector, no bitrate/codec/container constraint at this
    # stage (resolved 2026-07-15): a selector filtered by abr/codec here
    # caused "Requested format is not available" on every download tested,
    # since YouTube's actually-available formats vary per video and drift
    # over time. Grab whatever the best audio stream is; the quality
    # ceiling is enforced downward-only during the ffmpeg re-encode below.
    fmt = "bestaudio/best"

    postprocessor = {
        "key": "FFmpegExtractAudio",
        "preferredcodec": _CODEC_BY_FORMAT[output_format],
    }
    if output_format in LOSSY_FORMATS:
        if quality_kbps:
            postprocessor["preferredquality"] = str(quality_kbps)
        elif output_format in ("mp3", "ogg"):
            # No ceiling = best: ffmpeg's lame/vorbis default is ~128k —
            # request VBR quality 0 (~245k for mp3) instead.
            postprocessor["preferredquality"] = "0"
        elif output_format == "m4a":
            # AAC has no meaningful -q:a mapping; pin a rate above the
            # ~128-160k opus source. (opus target needs nothing: yt-dlp
            # stream-copies when source and target codecs match.)
            postprocessor["preferredquality"] = "192"

    if cookies_path == "unset":
        cookies_path = resolve_cookies_path()

    options = {
        "format": fmt,
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
        "postprocessors": [postprocessor],
        "ffmpeg_location": ffmpeg_path,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    if cookies_path:
        options["cookiefile"] = cookies_path
    if progress_callback is not None:
        # Transfer maps to 0-95%; the last 5% is the ffmpeg conversion.
        # Invoked on yt-dlp's worker thread — callbacks must be thread-safe.
        def hook(status: dict) -> None:
            if status.get("status") != "downloading":
                return
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            done = status.get("downloaded_bytes")
            if isinstance(total, (int, float)) and total > 0 and isinstance(done, (int, float)):
                try:
                    progress_callback(min(95, int(done / total * 95)))
                except Exception:
                    pass  # progress reporting must never kill the download

        options["progress_hooks"] = [hook]

    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise YtdlpDownloadError(f"yt-dlp failed for {video_id}: {exc}") from exc

    result = dest_dir / f"{video_id}.{output_format}"
    if not result.is_file():
        raise YtdlpDownloadError(
            f"yt-dlp reported success but {result.name} was not produced"
        )
    return result
